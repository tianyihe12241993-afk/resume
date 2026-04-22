# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A web platform that generates job-tailored `.docx` resumes at scale. Admins upload a base resume per candidate profile, paste job URLs into batches, and the system scrapes JDs → tailors via Claude API → writes `.docx` files. Bidders log in to download tailored resumes.

## Development Commands

```bash
# Backend (Python/FastAPI + SQLite)
cp .env.sample .env          # fill in ANTHROPIC_API_KEY, SESSION_SECRET, ADMIN_EMAIL
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh                     # uvicorn --reload on :8000

# Frontend (React/Vite/Tailwind)
cd frontend
npm install
npm run dev                  # Vite dev server on :5173, proxies /api + /download to :8000
npm run build                # outputs to app/static/ (served by FastAPI in prod)
npm run lint                 # ESLint
```

Both servers must run during development. The Vite proxy config is in `frontend/vite.config.ts`.

First login: set `ADMIN_EMAIL` in `.env`, start the backend, and the invite URL prints to the server console.

## Architecture

**Backend** — Python FastAPI app in `app/`:
- `main.py` — FastAPI app setup, file download routes, SPA fallback. Includes `api.router`.
- `api.py` — All JSON API endpoints under `/api`. Admin routes (`/api/admin/...`) and bidder routes (`/api/my/...`). Pydantic models for request bodies.
- `auth.py` — Password-based auth with bcrypt, signed session cookies (itsdangerous), invite tokens for onboarding new users.
- `pipeline.py` — Background `ThreadPoolExecutor` (default 6 workers) that processes each `JobUrl`: scrape → tailor → save. Fire-and-forget via `enqueue(job_url_id)`.
- `tailoring.py` — Core logic: parses `.docx` into `ResumeStruct` (AI-powered structure analysis with Haiku, cached by file hash), calls Claude (Sonnet) with XML-based prompt to tailor, writes back to `.docx` preserving formatting. The system prompt `TAILOR_SYSTEM` defines all tailoring rules.
- `scraping.py` — Per-ATS fetchers (Ashby, Lever, Greenhouse, Workday, SmartRecruiters, Rippling, Workable, Oracle HCM) + JSON-LD fallback + generic HTML extraction.
- `models.py` — SQLAlchemy ORM: `User`, `Profile`, `ProfileAccess`, `Batch`, `JobUrl`, `InviteToken`. Job statuses: `pending` → `fetching` → `tailoring` → `done` (or `needs_manual_jd` / `error`).
- `db.py` — SQLite engine, session factory, `init_db()` with hand-rolled `ALTER TABLE` migrations.
- `config.py` — All settings from env vars. Key: `TAILOR_MODEL` (Sonnet), `EXTRACT_MODEL` (Haiku), `MAX_URLS_PER_BATCH`.

**Frontend** — React SPA in `frontend/src/`:
- React 19 + React Router + TanStack Query + Tailwind CSS + Lucide icons
- `@` alias resolves to `frontend/src/` (configured in vite and tsconfig)
- Pages split by role: `pages/admin/` (Dashboard, ProfileDetail, batch views) and `pages/bidder/` (Profile, Batch)
- `lib/api.ts` — fetch wrapper for all `/api` calls

**Data flow**: Admin pastes URLs → `api.py` creates `Batch` + `JobUrl` rows → `pipeline.enqueue()` → worker thread scrapes JD, calls Claude to tailor, writes `.docx` → status updates in SQLite → frontend polls for changes.

## Key Patterns

- Per-profile tailor prompt override: `Profile.tailor_prompt` overrides the global `TAILOR_SYSTEM` when set.
- Resume structure detection uses Claude Haiku (cached by file SHA-256) with a heuristic fallback.
- The tailoring prompt uses XML input/output format — not JSON. Output is parsed with regex.
- `_repair_output()` patches missing sections from the original resume so partial Claude responses don't fail the whole job.
- `set_paragraph_text()` preserves `.docx` run formatting (bold lead-ins, majority-wins for multi-run paragraphs).
- Batches auto-merge: multiple URL submissions on the same day (Pacific time) for the same profile go into one batch.
- Duplicate URLs already `done` for a profile are silently skipped.
- DB migrations are inline in `db.py:_run_lightweight_migrations()` — add new columns there, not with Alembic.

## Environment Variables

See `.env.sample`. Required: `ANTHROPIC_API_KEY`, `SESSION_SECRET`, `ADMIN_EMAIL`. SMTP vars are optional (magic links print to console when unset).
