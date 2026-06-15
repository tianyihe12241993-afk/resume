"""Job discovery: JobSpy aggregator + ATS company boards, with dedup.

Sits IN FRONT of the scrape->tailor pipeline. Finds candidate jobs (URL + JD)
for a profile from two sources and removes anything the profile has already seen.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import scraping

from .db import Batch, JobUrl, Profile, SearchConfig


def _lines(value: str) -> list[str]:
    return [ln.strip() for ln in (value or "").splitlines() if ln.strip()]


def _csv(value: str) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


# Company-suffix noise that varies across platforms ("Stripe" vs "Stripe, Inc.").
_CO_SUFFIX = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|ag|bv|pvt|technologies|labs)\b",
    re.I,
)
# Trailing qualifiers in titles ("(Remote)", "- US", "[Contract]", req ids).
_TITLE_TAIL = re.compile(r"[\(\[\{].*?[\)\]\}]|\b(remote|hybrid|onsite|us|usa|emea)\b|\breq[-#\s]*\w+\b", re.I)


def _norm_company(c: str) -> str:
    c = (c or "").lower()
    c = re.sub(r"[^a-z0-9 ]", " ", c)
    c = _CO_SUFFIX.sub(" ", c)
    return re.sub(r"\s+", " ", c).strip()


def _norm_title(t: str) -> str:
    t = (t or "").lower()
    t = _TITLE_TAIL.sub(" ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _pair_key(company: str, title: str) -> tuple[str, str]:
    """Normalized (company, title) used to collapse the SAME role appearing on
    multiple platforms (Indeed / LinkedIn / Glassdoor) with different URLs."""
    return (_norm_company(company), _norm_title(title))


def norm_url(u: str) -> str:
    """Normalize a URL for dedup. Keeps the query string (Indeed encodes the job
    id there as ?jk=...); only canonicalizes host + trailing slash + case."""
    try:
        p = urlparse((u or "").strip())
    except Exception:
        return (u or "").strip().lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    base = f"{host}{p.path.rstrip('/')}"
    if p.query:
        base += "?" + p.query
    return base.lower()


def _safe(v) -> str:
    """Coerce a possibly-NaN/None pandas cell to a clean string."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and v != v:   # NaN
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def discover_jobspy(cfg: SearchConfig) -> list[dict]:
    """Broad aggregator search across configured sites x keywords x locations."""
    try:
        from jobspy import scrape_jobs
    except Exception:
        return []

    sites = _csv(cfg.sites) or ["indeed"]
    keywords = _lines(cfg.keywords)
    locations = _lines(cfg.locations) or ["Remote"]
    if not keywords:
        return []

    out: list[dict] = []
    for term in keywords:
        for loc in locations:
            try:
                df = scrape_jobs(
                    site_name=sites,
                    search_term=term,
                    location=loc,
                    results_wanted=int(cfg.results_limit or 40),
                    hours_old=int(cfg.hours_old or 168),
                    is_remote=bool(cfg.remote),
                    country_indeed="USA",
                    linkedin_fetch_description=True,
                )
            except Exception:
                continue
            if df is None or len(df) == 0:
                continue
            for _, r in df.iterrows():
                site = _safe(r.get("site")) or "jobspy"
                job_url = _safe(r.get("job_url"))
                direct = _safe(r.get("job_url_direct"))   # external/company apply URL
                # LinkedIn rows with no external apply URL are EasyApply
                # (you apply inside LinkedIn). The user doesn't want those.
                is_easyapply = site == "linkedin" and not direct
                if getattr(cfg, "exclude_easyapply", True) and is_easyapply:
                    continue
                # Prefer the direct company application URL when present — it's a
                # better tailoring/apply target than the aggregator page.
                url = direct or job_url
                if not url:
                    continue
                out.append({
                    "url": url,
                    "company": _safe(r.get("company")),
                    "title": _safe(r.get("title")),
                    "location": _safe(r.get("location")) or loc,
                    "description": _safe(r.get("description")),
                    "work_type": "remote" if bool(cfg.remote) else None,
                    "source": f"jobspy:{site}",
                })
    return out


def discover_ats(cfg: SearchConfig) -> list[dict]:
    """List all open roles from each configured ATS board ("provider:slug")."""
    out: list[dict] = []
    for entry in _lines(cfg.ats_companies):
        if ":" not in entry:
            continue
        provider, slug = entry.split(":", 1)
        out.extend(scraping.list_ats_postings(provider, slug))
    return out


def _existing_keys(db: Session, profile_id: int) -> tuple[set[str], set[tuple[str, str]]]:
    """URLs and (company,title) pairs this profile has already seen (any status)."""
    rows = (
        db.query(JobUrl.url, JobUrl.company, JobUrl.title)
        .join(Batch, JobUrl.batch_id == Batch.id)
        .filter(Batch.profile_id == profile_id)
        .all()
    )
    urls = {norm_url(u) for (u, _c, _t) in rows if u}
    pairs = {
        _pair_key(c, t)
        for (_u, c, t) in rows if c and t
    }
    return urls, pairs


def discover(db: Session, profile: Profile, cap: int = 120) -> list[dict]:
    """Run both sources for a profile, dedup against history and within results.

    Returns up to `cap` fresh job dicts (unscored). Does NOT write to the DB.
    """
    cfg = profile.search_config
    if cfg is None:
        return []

    raw = discover_jobspy(cfg) + discover_ats(cfg)

    seen_urls, seen_pairs = _existing_keys(db, profile.id)
    fresh: list[dict] = []
    for job in raw:
        url = (job.get("url") or "").strip()
        if not url:
            continue
        nu = norm_url(url)
        if nu in seen_urls:
            continue
        pair = _pair_key(job.get("company") or "", job.get("title") or "")
        if pair[0] and pair[1] and pair in seen_pairs:
            continue
        seen_urls.add(nu)
        if pair[0] and pair[1]:
            seen_pairs.add(pair)
        fresh.append(job)
        if len(fresh) >= cap:
            break
    return fresh
