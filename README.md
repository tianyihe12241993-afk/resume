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
# Edit .env — set ANTHROPIC_API_KEY and STUDIO_SESSION_SECRET. Optionally set
# STUDIO_ADMIN_EMAILS to your email (or just register first — you become admin).
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

## First login & admins

Visit `/signup` and create an account with any email + password.

**Who becomes an admin:**
- Any email listed in **`STUDIO_ADMIN_EMAILS`** (comma-separated) is auto-promoted
  to admin and auto-approved.
- **Bootstrap** — on a fresh clone with no admin configured, the **first account
  to register becomes the admin** automatically (zero config). Disable on public
  deployments with `STUDIO_BOOTSTRAP_ADMIN=0`.

Everyone else signs up **pending** and an admin approves them on the **Members**
page. So another operator can just **clone the repo → run it → register** and
they're the admin of their own instance.

**Roles:**
- **Admins** create profiles, upload base resumes, approve bidders, and assign
  profiles to bidders (per-profile or on the Members page).
- **Bidders** see everyone's work read-only, but can only open/download/work the
  profiles assigned to them. They add jobs, download tailored resumes, and
  upload them on job sites — with upload verification.

## Daily flow

1. Create a profile, upload its base `.docx`.
2. Optionally edit the per-profile tailoring prompt.
3. Paste URLs (one per line) into "New batch". Same-day pastes auto-merge.
4. Watch the batch page auto-refresh:
   - `pending/fetching/analyzing/tailoring` — in progress
   - `done` — `.docx`/`.pdf` ready (download buttons)
   - `needs_manual_jd` / `error` — shows a **classified failure reason + action**
     so a bidder knows exactly what to do (see below)
5. Mark each row as `applied` / `not_yet` / `error` / `not_remote` in the
   status dropdown.

### Failure reasons

When a JD can't be fetched, the status carries a precise category and action,
shown both inline per-job and in the dashboard's **"Needs attention"** panel:

| Reason | Meaning | Action |
|---|---|---|
| **Expired / filled** | 404/410 or "no longer accepting" | **Skip** — pasting won't help |
| **Login required** | sign-in wall (401/403) | Log in, copy the JD, paste it |
| **Blocked (bot check)** | captcha / Cloudflare | Open in browser, paste the JD |
| **Couldn't fetch** | timeout / DNS / 429 / 5xx | Retry, or paste the JD |
| **No JD found** | page loaded, no JD text | Paste the JD manually |
| **System error** | internal tailoring crash | Retry (not the posting's fault) |

## Resume archive (zip)

Tailored resumes can be bundled into a zip for interview prep / record-keeping,
foldered by candidate (`Joshua/Company__Role__jobN.docx` + `.pdf`):

- **Per batch** — the "Download all (zip)" button on a batch page.
- **Per day / everything** — the **"Today's resumes"** and **"All"** buttons on
  the dashboard. Endpoint: `GET /download/resumes/zip?date=YYYY-MM-DD` (US
  Pacific; omit `date` for the full archive).

For an automatic nightly backup, cron a `curl` of
`/download/resumes/zip?date=<today>` with an admin session cookie.

### Upload verification

After a bidder downloads a tailored resume and uploads it on the job site, the
browser extension hashes the uploaded file and confirms it matches the tailored
`.docx` **or** `.pdf` — surfaced as ✓ Verified / ⚠ wrong-file on the dashboard.
Works on iframe-embedded application forms (Greenhouse, ADP, SmartRecruiters).

## Adding jobs

Add jobs to a profile in any of these ways — all land in the same per-day batch
and run through the tailoring pipeline:

- **Browser extension (recommended)** — the floating **✦ Add** button on any job
  page, or the popup's bulk "queue open tabs". See [`extension/`](extension/).
- **Paste URLs** — the "New batch" box on a profile (one URL per line).

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

See [.env.sample](.env.sample). Highlights:

| Var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude API key |
| `STUDIO_SESSION_SECRET` | — | **Required in prod.** Cookie-signing secret |
| `STUDIO_ADMIN_EMAILS` | — | Comma-separated admin emails |
| `STUDIO_BOOTSTRAP_ADMIN` | `1` | First registrant becomes admin if no admin exists |
| `TAILOR_MODEL` | `claude-sonnet-4-6` | Bullet/summary writer |
| `JUDGE_MODEL` | `claude-sonnet-4-6` | Adjacency + skills judgment |
| `EXTRACT_MODEL` | `claude-haiku-4-5-...` | JD analysis / extraction |
| `FINAL_ADJACENCY` | `1` | Re-score final coverage (set `0` for a bit more speed) |
| `STUDIO_WORKERS` | `8` | Concurrent tailoring jobs (lower if you hit 429s) |
| `STUDIO_GIPHY_KEY` | — | Enables GIF search in team chat |

## Production notes

- **Run a single uvicorn *process*.** The real-time chat and the job queue are
  in-process — `uvicorn --workers >1` would break them. `STUDIO_WORKERS` is the
  internal thread pool and is independent.
  ```bash
  python -m uvicorn tailor_studio.main:app --host 0.0.0.0 --port 8001
  ```
- **PDF export needs Microsoft Word or LibreOffice** on the host. It auto-detects
  LibreOffice (`soffice`) first, then Word via COM (Windows). On a headless
  server, install LibreOffice or PDF generation will fail (the `.docx` still works).
- **Rate limits** — at high volume, confirm your Anthropic tier's RPM/TPM and
  turn `STUDIO_WORKERS` down if you see 429s.

## Expose to internet

```bash
cloudflared tunnel --url http://127.0.0.1:8001
```

Returns a public `https://xxx.trycloudflare.com` URL.
