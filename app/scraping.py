"""Job-posting scraper with per-board fallbacks."""
from __future__ import annotations

import html as _html
import json as _json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


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
                return {
                    "company": (
                        data.get("company_name") or slug.replace("_", " ").title()
                    ),
                    "title": data.get("title", ""),
                    "location": (data.get("location") or {}).get("name", ""),
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
        return {
            "company": (data.get("company") or {}).get("name", m_co.group(1)),
            "title": data.get("name", ""),
            "location": loc.get("fullLocation") or loc.get("city", ""),
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
        return {
            "company": (api_data.get("jobBoard") or {}).get("name")
                or (job.get("company") or {}).get("name", ""),
            "title": job.get("name") or job.get("title", ""),
            "location": (job.get("workLocation") or {}).get("description", ""),
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
            if desc and len(desc) >= 200:
                return {
                    "company": company,
                    "title": d.get("title", "") or "",
                    "location": location,
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


def fetch_job_posting(url: str) -> dict:
    """Return {company, title, location, description}.

    Raises RuntimeError on fetch failure.
    """
    host = urlparse(url).netloc.lower()

    if "ashbyhq.com" in host:
        info = _fetch_ashby(url)
        if info and info.get("description"):
            return info
    if "lever.co" in host:
        info = _fetch_lever(url)
        if info and info.get("description"):
            return info
    if "greenhouse.io" in host:
        info = _fetch_greenhouse(url)
        if info and info.get("description"):
            return info
    if "myworkdayjobs.com" in host:
        info = _fetch_workday(url)
        if info and info.get("description"):
            return info
    if host == "jobs.smartrecruiters.com":
        info = _fetch_smartrecruiters(url)
        if info and info.get("description"):
            return info
    if host == "ats.rippling.com":
        info = _fetch_rippling(url)
        if info and info.get("description"):
            return info
    if "oraclecloud.com" in host:
        info = _fetch_oracle_hcm(url)
        if info and info.get("description"):
            return info
    if host == "apply.workable.com":
        info = _fetch_workable(url)
        if info and info.get("description"):
            return info

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
            return info

    last_err: Optional[Exception] = None
    for u in candidates:
        try:
            r = _get(u)
            if r.status_code == 200 and len(r.text) > 500:
                return _extract_from_html(r.text)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not fetch job page: {url} ({last_err})")
