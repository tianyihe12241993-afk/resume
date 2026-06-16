"""Job-posting scraper with per-board fallbacks."""
from __future__ import annotations

import html as _html
import json as _json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .work_type import classify_work_type, normalize_work_type
from .llm import make_client


def _finalize(info: Optional[dict]) -> Optional[dict]:
    """Fill in ``work_type`` via the deterministic classifier when the per-ATS
    extractor did not produce one. Never overwrites a structured value. Safe
    to call on a None input."""
    if not info:
        return info
    wt = normalize_work_type(info.get("work_type"))
    if not wt:
        wt = classify_work_type(
            title=info.get("title") or "",
            location=info.get("location") or "",
            description=info.get("description") or "",
        )
    info["work_type"] = wt
    return info


def _html_to_text(value: str) -> str:
    """Turn HTML (possibly entity-encoded) into clean plain text."""
    if not value:
        return ""
    # Handle double-escaped HTML like "&lt;p&gt;..." returned by some APIs.
    unescaped = _html.unescape(value)
    text = BeautifulSoup(unescaped, "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/json,*/*"}


class JobFetchError(RuntimeError):
    """A scrape failure classified into an actionable category so the UI can
    tell the bidder exactly what to do (skip / paste / retry / log in).

    category ∈ {expired, login_required, blocked, fetch_failed, empty_jd}.
    `message` is bidder-facing; `status_code` is the last HTTP status seen.
    """
    def __init__(self, category: str, message: str, status_code=None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code


# Page-text signals that a posting is closed (checked when a page DID load).
_EXPIRED_SIGNALS = (
    "no longer accepting", "no longer available", "position has been filled",
    "this job is no longer", "posting has closed", "posting is closed",
    "job not found", "position is closed", "this role is closed",
    "applications are closed", "we are no longer accepting", "req closed",
    "this opening is closed", "no longer open",
)
_LOGIN_SIGNALS = (
    "sign in to apply", "log in to apply", "please sign in", "please log in",
    "create an account", "you must be logged in", "authentication required",
)
_BLOCK_SIGNALS = (
    "captcha", "cloudflare", "are you a robot", "verify you are human",
    "access denied", "request blocked", "unusual traffic", "px-captcha",
)


def _classify_fetch_failure(url, status, html, err) -> JobFetchError:
    """Turn a raw fetch failure into a categorized, actionable JobFetchError."""
    text = (html or "").lower()
    es = str(err or "").lower()

    if status in (404, 410):
        return JobFetchError(
            "expired",
            f"Posting is gone (HTTP {status}) — expired, filled, or the link is wrong. Skip this one.",
            status)
    if status in (401, 403):
        if any(k in text for k in _BLOCK_SIGNALS):
            return JobFetchError(
                "blocked",
                f"Site blocked automated access with a bot check (HTTP {status}). Open it in your browser and paste the JD manually.",
                status)
        if any(k in text for k in _LOGIN_SIGNALS) or "login" in text or "sign in" in text:
            return JobFetchError(
                "login_required",
                f"This posting requires sign-in to view (HTTP {status}). Log in, copy the JD, and paste it manually.",
                status)
        return JobFetchError(
            "blocked",
            f"Access denied (HTTP {status}). Open it in your browser and paste the JD manually.",
            status)
    if status == 429:
        return JobFetchError(
            "fetch_failed",
            "Site is rate-limiting us (HTTP 429). Wait a few minutes and retry, or paste the JD manually.",
            status)
    if isinstance(status, int) and status >= 500:
        return JobFetchError(
            "fetch_failed",
            f"Site's server errored (HTTP {status}). Retry later, or paste the JD manually.",
            status)

    # Page loaded (or we have HTML) but extraction failed — look for signals.
    if any(k in text for k in _EXPIRED_SIGNALS):
        return JobFetchError(
            "expired",
            "The page says this job is closed / no longer accepting applications. Skip this one.",
            status)
    if any(k in text for k in _LOGIN_SIGNALS):
        return JobFetchError(
            "login_required",
            "The job is behind a login. Sign in, copy the JD, and paste it manually.",
            status)
    if any(k in text for k in _BLOCK_SIGNALS):
        return JobFetchError(
            "blocked",
            "The site blocked automated access (bot check). Open it in your browser and paste the JD manually.",
            status)

    # No HTTP response at all → network-level failure.
    if status is None and not html:
        if "timeout" in es or "timed out" in es:
            return JobFetchError(
                "fetch_failed",
                "The page timed out before loading. Retry shortly, or open it in your browser and paste the JD manually.")
        if any(k in es for k in ("getaddrinfo", "name or service", "nodename", "failed to resolve", "connection", "refused")):
            return JobFetchError(
                "fetch_failed",
                "Couldn't connect to the site (it may be down or the link broken). Check the URL, or paste the JD manually.")
        return JobFetchError(
            "fetch_failed",
            "Couldn't fetch the page. Open it in your browser and paste the JD manually.")

    # Got a page but no JD text found.
    return JobFetchError(
        "empty_jd",
        "Loaded the page but couldn't find the job description automatically. Open it and paste the JD manually.",
        status)


def _get(url: str, timeout: int = 20) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)


def _fetch_ashby(url: str) -> Optional[dict]:
    path = urlparse(url).path.strip("/").split("/")
    if len(path) < 2:
        return None
    slug, job_id = path[0], path[1]
    api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
        for posting in data.get("jobs", []):
            if posting.get("id") == job_id:
                return {
                    "company": data.get("name") or slug,
                    "title": posting.get("title", ""),
                    "location": posting.get("location", ""),
                    "work_type": posting.get("workplaceType"),
                    "description": (
                        posting.get("descriptionPlain")
                        or _html_to_text(posting.get("descriptionHtml", ""))
                    ),
                }
    except Exception:
        return None
    return None


def _fetch_lever(url: str) -> Optional[dict]:
    path = urlparse(url).path.strip("/").split("/")
    if len(path) < 2:
        return None
    slug, job_id = path[0], path[1]
    api = f"https://api.lever.co/v0/postings/{slug}/{job_id}?mode=json"
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
        desc_html = data.get("description", "") + "\n"
        for block in data.get("lists", []):
            desc_html += f"\n<h3>{block.get('text','')}</h3>" + block.get("content", "")
        desc_html += "\n" + data.get("additional", "")
        return {
            "company": slug,
            "title": data.get("text", ""),
            "location": (data.get("categories") or {}).get("location", ""),
            "work_type": (data.get("workplaceType")
                          or (data.get("categories") or {}).get("commitment")
                          or (data.get("categories") or {}).get("workplaceType")),
            "description": _html_to_text(desc_html),
        }
    except Exception:
        return None


def _fetch_greenhouse(url: str) -> Optional[dict]:
    qs = parse_qs(urlparse(url).query)
    slug = (qs.get("for") or [None])[0]
    token = (qs.get("token") or [None])[0]
    if slug and token:
        api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{token}"
        try:
            r = _get(api)
            if r.status_code == 200:
                data = r.json()
                # Greenhouse has no first-class workplace-type field.
                # Some boards stash it in `metadata` as a tagged value;
                # otherwise the location.name string carries the signal
                # and the classifier picks it up.
                wt_hint = None
                for m in (data.get("metadata") or []):
                    if not isinstance(m, dict):
                        continue
                    name = (m.get("name") or "").lower()
                    val = m.get("value")
                    if "remote" in name or "workplace" in name or "work type" in name:
                        if isinstance(val, str):
                            wt_hint = val
                            break
                        if isinstance(val, list) and val:
                            wt_hint = str(val[0])
                            break
                return {
                    "company": (
                        data.get("company_name") or slug.replace("_", " ").title()
                    ),
                    "title": data.get("title", ""),
                    "location": (data.get("location") or {}).get("name", ""),
                    "work_type": wt_hint,
                    "description": _html_to_text(data.get("content", "")),
                }
        except Exception:
            pass
    try:
        r = _get(url)
        if r.status_code == 200:
            return _extract_from_html(r.text, fallback_company=slug or "")
    except Exception:
        pass
    return None


def _fetch_workday(url: str) -> Optional[dict]:
    """Workday SPAs (*.myworkdayjobs.com) expose a JSON endpoint under /wday/cxs/.

    Example URL:
      https://alteryx.wd108.myworkdayjobs.com/AlteryxCareers/job/Colorado/Software-Engineer_R11934
    Maps to:
      https://alteryx.wd108.myworkdayjobs.com/wday/cxs/alteryx/AlteryxCareers/job/Software-Engineer_R11934
    """
    parts = urlparse(url)
    host_parts = parts.netloc.split(".")
    if len(host_parts) < 4 or "myworkdayjobs" not in parts.netloc:
        return None
    tenant = host_parts[0]
    path_bits = [p for p in parts.path.split("/") if p]
    if "job" not in path_bits:
        return None
    site = path_bits[0]
    # Job slug is the last path segment (drop '/apply' if present).
    tail = path_bits[-1]
    if tail in ("apply",):
        tail = path_bits[-2]
    api = f"{parts.scheme}://{parts.netloc}/wday/cxs/{tenant}/{site}/job/{tail}"
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
        info = data.get("jobPostingInfo") or {}
        return {
            "company": tenant.replace("-", " ").title(),
            "title": info.get("title", ""),
            "location": info.get("location", ""),
            "description": _html_to_text(info.get("jobDescription", "")),
        }
    except Exception:
        return None


def _fetch_smartrecruiters(url: str) -> Optional[dict]:
    """https://jobs.smartrecruiters.com/oneclick-ui/company/<name>/publication/<uuid>/…"""
    path = urlparse(url).path
    m_co = re.search(r"/company/([^/]+)/", path)
    m_pub = re.search(r"/publication/([0-9a-f-]+)", path)
    if not (m_co and m_pub):
        return None
    api = f"https://api.smartrecruiters.com/v1/companies/{m_co.group(1)}/postings/{m_pub.group(1)}"
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
        job_ad = data.get("jobAd", {}) or {}
        sections = job_ad.get("sections", {}) or {}
        bits: list = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            val = (sections.get(key) or {}).get("text", "")
            if val:
                bits.append(_html_to_text(val))
        loc = data.get("location", {}) or {}
        wt_hint = None
        if loc.get("remote") is True:
            wt_hint = "remote"
        return {
            "company": (data.get("company") or {}).get("name", m_co.group(1)),
            "title": data.get("name", ""),
            "location": loc.get("fullLocation") or loc.get("city", ""),
            "work_type": wt_hint,
            "description": "\n\n".join(b for b in bits if b),
        }
    except Exception:
        return None


def _fetch_rippling(url: str) -> Optional[dict]:
    """ats.rippling.com is a Next.js SPA; JD is in __NEXT_DATA__ at
    props.pageProps.apiData.jobPost.description.{company,role}."""
    try:
        r = _get(url)
        if r.status_code != 200:
            return None
        m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
            r.text, re.DOTALL,
        )
        if not m:
            return None
        data = _json.loads(m.group(1))
    except Exception:
        return None
    try:
        api_data = data["props"]["pageProps"]["apiData"]
        job = api_data.get("jobPost") or {}
        descr = job.get("description") or {}
        desc_html = "\n".join(
            (descr.get(k) or "")
            for k in ("company", "role", "benefits", "pay")
        )
        work_loc = job.get("workLocation") or {}
        wt_hint = (work_loc.get("workplaceType")
                   or work_loc.get("workType")
                   or job.get("workplaceType"))
        return {
            "company": (api_data.get("jobBoard") or {}).get("name")
                or (job.get("company") or {}).get("name", ""),
            "title": job.get("name") or job.get("title", ""),
            "location": work_loc.get("description", ""),
            "work_type": wt_hint,
            "description": _html_to_text(desc_html),
        }
    except Exception:
        return None


def _fetch_workable(url: str) -> Optional[dict]:
    """apply.workable.com uses /<slug>/j/<shortcode>/ — fetch the JSON at
    /api/v1/accounts/<slug>/jobs/<shortcode>."""
    parts = urlparse(url)
    m = re.match(r"/([^/]+)/j/([^/]+)", parts.path)
    if not m:
        return None
    slug, shortcode = m.group(1), m.group(2)
    api = f"https://apply.workable.com/api/v1/accounts/{slug}/jobs/{shortcode}"
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    parts_html: list = []
    for key in ("description", "requirements", "benefits"):
        v = data.get(key)
        if v:
            parts_html.append(v)
    loc = data.get("location") or {}
    city = loc.get("city", "") or ""
    country = loc.get("country", "") or ""
    location = ", ".join(filter(None, [city, country]))
    return {
        "company": (data.get("account") or {}).get("name")
            or slug.replace("-dot-", ".").replace("-", " ").title(),
        "title": data.get("title", ""),
        "location": location,
        "description": _html_to_text("\n".join(parts_html)),
    }


def _fetch_oracle_hcm(url: str) -> Optional[dict]:
    """Oracle Cloud HCM (fa.*.oraclecloud.com) uses /hcmUI/… for the SPA and
    /hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/<id> for data.
    """
    parts = urlparse(url)
    m = re.search(r"/job/(\d+)", parts.path)
    if not m:
        return None
    job_id = m.group(1)
    api = (
        f"{parts.scheme}://{parts.netloc}"
        f"/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{job_id}"
        "?expand=all"
    )
    try:
        r = _get(api)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    # Oracle returns nested fields; description + shortDescription both contain HTML.
    desc_html = "\n".join(
        (data.get(k) or "")
        for k in ("ExternalDescriptionStr", "ExternalDescription", "ShortDescription", "Description")
    )
    # Also look inside "items" arrays (qualifications / responsibilities).
    for key in ("ExternalQualificationsStr", "ExternalResponsibilitiesStr",
                "ExternalAdditionalInformationStr", "CorporateDescriptionStr"):
        v = data.get(key)
        if v:
            desc_html += "\n" + v
    return {
        "company": data.get("OrganizationName") or data.get("PrimaryWorkLocationName") or "",
        "title": data.get("Title") or "",
        "location": data.get("PrimaryLocation") or data.get("PrimaryWorkLocationName") or "",
        "description": _html_to_text(desc_html),
    }


def _fetch_jsonld(url: str) -> Optional[dict]:
    """Generic fallback: look for a <script type="application/ld+json"> block
    containing a schema.org JobPosting. Many ATSs embed this for SEO even if
    the page itself is JS-rendered (e.g. Recruiterflow, some Workdays)."""
    try:
        r = _get(url)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>',
        html, re.DOTALL,
    ):
        try:
            data = _json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for d in items:
            if not isinstance(d, dict):
                continue
            t = d.get("@type")
            if t != "JobPosting" and not (isinstance(t, list) and "JobPosting" in t):
                continue
            company = ""
            org = d.get("hiringOrganization")
            if isinstance(org, dict):
                company = org.get("name", "") or ""
            elif isinstance(org, str):
                company = org
            location = ""
            loc = d.get("jobLocation")
            if isinstance(loc, dict):
                addr = loc.get("address") or {}
                if isinstance(addr, dict):
                    location = ", ".join(
                        filter(None, [addr.get("addressLocality"), addr.get("addressRegion")])
                    )
            elif isinstance(loc, list) and loc:
                first = loc[0] or {}
                addr = (first.get("address") or {}) if isinstance(first, dict) else {}
                if isinstance(addr, dict):
                    location = ", ".join(
                        filter(None, [addr.get("addressLocality"), addr.get("addressRegion")])
                    )
            desc_html = d.get("description", "") or ""
            desc = _html_to_text(desc_html)
            wt_hint = None
            jlt = d.get("jobLocationType")
            if isinstance(jlt, str) and "telecommute" in jlt.lower():
                wt_hint = "remote"
            if desc and len(desc) >= 200:
                return {
                    "company": company,
                    "title": d.get("title", "") or "",
                    "location": location,
                    "work_type": wt_hint,
                    "description": desc,
                }
    return None


def _extract_from_html(html: str, fallback_company: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    for sel in ["h1", ".app-title", "[data-test='job-title']"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {
        "company": fallback_company,
        "title": title,
        "location": "",
        "description": text,
    }


def _haiku_extract_from_html(html: str, url: str) -> Optional[dict]:
    """Last-ditch fallback: ask Haiku to pull the JD out of raw HTML.

    Useful for ATS pages where the job content is hiding in a script tag,
    a non-standard JSON-LD shape, an embedded data island, or a place our
    heuristic selectors didn't anticipate. For pure JS-only SPAs whose
    response body has no JD content at all (Gem, ADP, Metacareers...),
    Haiku returns empty and we still fall through to needs_manual_jd.

    Returns {"company","title","location","description"} on success or
    None on failure. Never raises — best-effort only.
    """
    if not html or len(html) < 500:
        return None

    # Strip <style> entirely (no signal) and trim <script> tags but keep their
    # text content so embedded JSON state survives. Cap at ~30K chars going
    # to Haiku — we only need enough for it to find the JD pattern.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "noscript", "svg", "iframe", "link"]):
        tag.decompose()

    # For SPA pages whose body is empty, the only signal is embedded JSON in
    # <script> tags. Concatenate the inner text of the high-value script tags
    # ahead of the rest so it survives the 30K truncation.
    json_priority: list[str] = []
    for s in soup.find_all("script"):
        sid = (s.get("id") or "").lower()
        stype = (s.get("type") or "").lower()
        if (sid in ("__next_data__", "__nuxt__", "__apollo_state__")
                or "ld+json" in stype
                or "application/json" in stype):
            txt = (s.string or s.get_text("") or "")[:20_000]
            if txt.strip():
                json_priority.append(txt)
    cleaned_html = str(soup)
    if json_priority:
        cleaned_html = "\n\n".join(json_priority) + "\n\n" + cleaned_html
    if len(cleaned_html) > 30_000:
        cleaned_html = cleaned_html[:30_000]

    try:
        # Lazy import to avoid pulling Anthropic into hot path when unused.
        from . import config
        from anthropic import Anthropic
        if not config.ANTHROPIC_API_KEY:
            return None
        client = make_client()
        prompt = (
            "Extract a job posting from this raw HTML. The content may be in a "
            "script tag with embedded JSON, a JSON-LD block, hidden meta tags, "
            "or page text — find it wherever it lives. If the HTML is just a "
            "JS shell with no real JD content, return empty strings.\n\n"
            f"URL: {url}\n\n"
            f"HTML:\n{cleaned_html}\n\n"
            'Return <json>{"company": "...", "title": "...", "location": "...", '
            '"work_type": "remote|hybrid|onsite|unknown", '
            '"description": "..."}</json>. The description should be the full job '
            "text, plain (entities decoded), no HTML tags. "
            "work_type: 'remote' if fully remote / WFH / anywhere, "
            "'hybrid' if a mix or N days in-office, 'onsite' if office/no remote, "
            "'unknown' if you can't tell."
        )
        resp = client.messages.create(
            model=config.EXTRACT_MODEL,
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        m = re.search(r"<json>\s*(\{.*?\})\s*</json>", text, re.DOTALL) \
            or re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL) \
            or re.search(r"(\{.*\})", text, re.DOTALL)
        if not m:
            return None
        data = _json.loads(m.group(1))
    except Exception:
        return None

    desc = (data.get("description") or "").strip()
    if len(desc) < 200:
        return None  # Haiku also gave up — fall through to needs_manual_jd
    return {
        "company":  (data.get("company")  or "").strip(),
        "title":    (data.get("title")    or "").strip(),
        "location": (data.get("location") or "").strip(),
        "work_type": (data.get("work_type") or "").strip() or None,
        "description": desc,
    }


def _fetch_with_playwright(url: str) -> Optional[dict]:
    """Last-resort SPA-rendered fetch. Launches a headless Chromium, renders
    the page with JS, then runs the rendered HTML through the existing
    extractors (`_extract_from_html` heuristic, then `_haiku_extract_from_html`).

    Returns ``None`` on any failure — caller treats this as 'no info' and
    raises the usual scrape-failed error.

    Heavy: ~2–5s per call. Only invoked after all plain-HTTP fallbacks have
    returned empty.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    html = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                # Block heavy resources we never need for text extraction.
                def _route(route):
                    if route.request.resource_type in ("image", "media", "font"):
                        route.abort()
                    else:
                        route.continue_()
                ctx.route("**/*", _route)

                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                except Exception:
                    # Even on nav timeout, the partial DOM may have what we need.
                    pass
                # Hash-routed SPAs (JobDiva, Bullhorn OSCP, …) settle the JD
                # *after* networkidle, so wait on actual body text length.
                # Fall through on timeout — the partial DOM is still worth a try.
                try:
                    page.wait_for_function(
                        "document.body && document.body.innerText.length > 1500",
                        timeout=15_000,
                    )
                except Exception:
                    try:
                        page.wait_for_load_state("networkidle", timeout=4_000)
                    except Exception:
                        pass
                html = page.content() or ""
            finally:
                browser.close()
    except Exception:
        return None

    if not html or len(html) < 500:
        return None
    info = _extract_from_html(html)
    if len((info.get("description") or "")) >= 400:
        return info
    haiku = _haiku_extract_from_html(html, url)
    if haiku and haiku.get("description"):
        return haiku
    return None


def fetch_job_posting(url: str, *, bypass_cache: bool = False) -> dict:
    """Return {company, title, location, description}.

    Results are cached on disk for 7 days (see app/scrape_cache.py). Pass
    bypass_cache=True to force a fresh network fetch — e.g. when a user
    explicitly requests a re-scrape because the cached JD looks wrong.

    Raises RuntimeError on fetch failure.
    """
    from . import scrape_cache

    if not bypass_cache:
        hit = scrape_cache.get(url)
        if hit is not None:
            # Pre-existing cache entries pre-date the work_type field. Run
            # _finalize on the way out: it preserves a normalized value if
            # present, otherwise runs the classifier.
            return _finalize(hit)
    info = _fetch_job_posting_uncached(url)
    scrape_cache.put(url, info)
    return info


def _fetch_job_posting_uncached(url: str) -> dict:
    host = urlparse(url).netloc.lower()

    if "ashbyhq.com" in host:
        info = _fetch_ashby(url)
        if info and info.get("description"):
            return _finalize(info)
    if "lever.co" in host:
        info = _fetch_lever(url)
        if info and info.get("description"):
            return _finalize(info)
    if "greenhouse.io" in host:
        info = _fetch_greenhouse(url)
        if info and info.get("description"):
            return _finalize(info)
    if "myworkdayjobs.com" in host:
        info = _fetch_workday(url)
        if info and info.get("description"):
            return _finalize(info)
    if host == "jobs.smartrecruiters.com":
        info = _fetch_smartrecruiters(url)
        if info and info.get("description"):
            return _finalize(info)
    if host == "ats.rippling.com":
        info = _fetch_rippling(url)
        if info and info.get("description"):
            return _finalize(info)
    if "oraclecloud.com" in host:
        info = _fetch_oracle_hcm(url)
        if info and info.get("description"):
            return _finalize(info)
    if host == "apply.workable.com":
        info = _fetch_workable(url)
        if info and info.get("description"):
            return _finalize(info)

    candidates = [url]
    if url.endswith("/application"):
        candidates.append(url.rsplit("/application", 1)[0])
    if url.endswith("/apply"):
        candidates.append(url.rsplit("/apply", 1)[0])

    # Generic JSON-LD fallback — many ATSs embed schema.org JobPosting for SEO
    # even when the main page is JS-rendered. Worth trying before giving up.
    for u in candidates:
        info = _fetch_jsonld(u)
        if info and info.get("description"):
            return _finalize(info)

    last_err: Optional[Exception] = None
    last_html: Optional[str] = None
    last_url_used: Optional[str] = None
    last_status: Optional[int] = None
    for u in candidates:
        try:
            r = _get(u)
            last_status = r.status_code
            if r.status_code == 200 and len(r.text) > 500:
                info = _extract_from_html(r.text)
                # Description is "real" if we got >= 400 chars from heuristic
                # extraction. Otherwise stash the HTML for the Haiku fallback.
                if len(info.get("description") or "") >= 400:
                    return _finalize(info)
                last_html = r.text
                last_url_used = u
            elif r.status_code != 200:
                # Keep the body of an error page so the classifier can read
                # "no longer accepting" / login / captcha signals from it.
                last_html = last_html or (r.text if r.text else None)
        except Exception as e:
            last_err = e

    # Last-ditch: Haiku reads the raw HTML and tries to find embedded JD.
    if last_html:
        haiku_info = _haiku_extract_from_html(last_html, last_url_used or url)
        if haiku_info and haiku_info.get("description"):
            return _finalize(haiku_info)

    # SPA fallback: render the page in Chromium and try the extractors again.
    # Fires for ATS portals that ship an empty shell to plain HTTP (ADP,
    # JobDiva, Bullhorn OSCP, Zoho Recruit, Dayforce, RippleHire, SaasHR, …).
    pw_info = _fetch_with_playwright(url)
    if pw_info and pw_info.get("description"):
        return _finalize(pw_info)

    # Everything failed — classify into an actionable category for the bidder.
    raise _classify_fetch_failure(url, last_status, last_html, last_err)
