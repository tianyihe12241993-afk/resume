"""Job-posting scraper with per-board fallbacks."""
from __future__ import annotations

import html as _html
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

    candidates = [url]
    if url.endswith("/application"):
        candidates.append(url.rsplit("/application", 1)[0])
    if url.endswith("/apply"):
        candidates.append(url.rsplit("/apply", 1)[0])

    last_err: Optional[Exception] = None
    for u in candidates:
        try:
            r = _get(u)
            if r.status_code == 200 and len(r.text) > 500:
                return _extract_from_html(r.text)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not fetch job page: {url} ({last_err})")
