# resume-tailor-studio

A web platform for generating job-tailored `.docx` (and `.pdf`) resumes at scale.
Each user uploads a base resume per profile, pastes job URLs into batches, and
the system scrapes each JD, runs a constrained-rewrite tailoring pipeline via
Claude, and produces a downloadable file.

## Stack

- **Backend** — FastAPI + SQLite + SQLAlchemy ([tailor_studio/](tailor_studio/))
- **Frontend** — React 19 + Vite + Tailwind + TanStack Query
  ([tailor_studio/web/](tailor_studio/web/))
- **Tailoring pipeline** — Python modules under [app/](app/), reused as a
  library:
  - [jd_analyzer.py](app/jd_analyzer.py) — Haiku spec extraction (cached)
  - [coverage_map.py](app/coverage_map.py) — deterministic JD↔resume mapping
  - [adjacency_proposer.py](app/adjacency_proposer.py) — adjacent-term proposals
  - [bullet_rewriter.py](app/bullet_rewriter.py) — per-bullet Sonnet rewrite
    with prompt caching
  - [bullet_validator.py](app/bullet_validator.py) — deterministic guardrails
  - [tailoring.py](app/tailoring.py) — `.docx` IO + structure detection
  - [scraping.py](app/scraping.py) — per-ATS scrapers + JSON-LD fallback
  - [scrape_cache.py](app/scrape_cache.py) — URL-keyed disk cache (7d TTL)

## Quick Start

```bash
git clone https://github.com/tianyihe12241993-afk/resume.git
cd resume

# 1. Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
# Edit .env — set ANTHROPIC_API_KEY at minimum
.venv/Scripts/python -m uvicorn tailor_studio.main:app --reload --port 8001
# Backend serves on http://127.0.0.1:8001

# 2. Frontend (separate terminal)
cd tailor_studio/web
npm install
npm run dev
# Vite dev server on http://127.0.0.1:5173 (proxies /api + /download to :8001)
```

For production: `cd tailor_studio/web && npm run build` outputs static assets
to `tailor_studio/static/`, which FastAPI serves directly from `/`.

## First login

Visit `/signup`, create an account with any email + password. Multi-user — each
user only sees their own profiles, batches, and tailored outputs.

## Daily flow

1. Create a profile, upload its base `.docx`.
2. Optionally edit the per-profile tailoring prompt.
3. Paste URLs (one per line) into "New batch". Same-day pastes auto-merge.
4. Watch the batch page auto-refresh:
   - `pending/fetching/analyzing/tailoring` — in progress
   - `done` — `.docx` ready (download inline; click "pdf" to generate `.pdf`)
   - `needs_manual_jd` — scraper couldn't read enough; paste JD by hand
   - `error` — click the retry icon
5. Mark each row as `applied` / `not_yet` / `error` / `not_remote` in the
   status dropdown.

## Tailoring guarantees

- **Never invents** tech, companies, projects, metrics, titles, or dates.
- **Never adds or drops bullets** — rewording and reordering only.
- Per-bullet rewrites run through a deterministic validator that reverts any
  rewrite violating the constraints.
- Every Claude call is content-addressed cached on disk, so re-running the
  same `(JD, profile)` is free.

## Supported job boards

Ashby, Lever, Greenhouse, Workday, SmartRecruiters, Rippling, Workable, Oracle
HCM. Plus JSON-LD fallback for any board exposing schema.org/JobPosting and a
generic HTML extractor + Haiku rescue for everything else.

## Environment variables

See [.env.sample](.env.sample). Required: `ANTHROPIC_API_KEY`,
`SESSION_SECRET`. Optional: `TAILOR_MODEL` (default Sonnet 4.6),
`EXTRACT_MODEL` (default Haiku 4.5), `STUDIO_WORKERS` (default 4).

## Expose to internet

```bash
cloudflared tunnel --url http://127.0.0.1:8001
```

Returns a public `https://xxx.trycloudflare.com` URL.
