# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repo.

## What This Is

A multi-user web platform that generates job-tailored `.docx` (and `.pdf`)
resumes at scale. Each user uploads a base resume per profile, pastes job
URLs into batches, and the system scrapes the JD → runs a constrained-rewrite
tailoring pipeline via Claude → writes a downloadable file.

## Development Commands

```bash
# Backend (FastAPI + SQLite)
cp .env.sample .env            # fill in ANTHROPIC_API_KEY, SESSION_SECRET
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
.venv/Scripts/python -m uvicorn tailor_studio.main:app --reload --port 8001

# Frontend (React/Vite/Tailwind)
cd tailor_studio/web
npm install
npm run dev                    # Vite on :5173, proxies /api + /download to :8001
npm run build                  # outputs to tailor_studio/static/ for prod
```

## Architecture

**Backend** — FastAPI app in `tailor_studio/`:
- `main.py` — app setup, `/download/{jid}/{docx,pdf}` routes, SPA fallback.
- `api.py` — all JSON endpoints under `/api`. Every handler scopes by
  `Depends(auth.require_user)` so users only see their own data.
- `auth.py` — bcrypt password hashing + signed session cookies
  (`itsdangerous`).
- `db.py` — SQLAlchemy models: `User`, `Profile`, `Batch`, `JobUrl`.
  Inline `ALTER TABLE` migrations in `init_db()` — no Alembic.
- `pipeline.py` — `ThreadPoolExecutor` (default 4 workers) that processes
  each `JobUrl`: scrape → analyze → coverage → bullet-rewrite → assemble.
- `pdf_export.py` — `docx2pdf` wrapped in `pythoncom.CoInitialize()` for
  Windows Word-COM thread safety.
- `storage.py` — filesystem paths for base resumes and generated outputs.
- `config.py` — env-var settings.

**Tailoring pipeline** — Python modules in `app/`, imported by
`tailor_studio.pipeline` as a library:
- `jd_analyzer.py` — Haiku extracts structured spec (hard skills, weights,
  must-have phrases). Cached on disk by `sha256(title + company + jd_text)`.
- `coverage_map.py` — deterministic mapping of spec terms to resume
  evidence (covered_exact / covered_adjacent / gap). No LLM call.
- `adjacency_proposer.py` — proposes "term X in JD is plausibly covered by
  resume evidence Y." Cached.
- `bullet_rewriter.py` — one Sonnet call per bullet with prompt caching
  (`cache_control: ephemeral` on the shared system prompt + JD context).
  Output flows through `bullet_validator.py` (deterministic guardrails).
- `tailoring.py` — `ResumeStruct` parsing, `apply_tailoring()` writes back
  to `.docx` preserving run-level formatting.
- `scraping.py` — per-ATS fetchers (Ashby, Lever, Greenhouse, Workday,
  SmartRecruiters, Rippling, Workable, Oracle HCM) + JSON-LD fallback +
  generic HTML + Haiku rescue.
- `scrape_cache.py` — URL-keyed disk cache, 7-day TTL.

**Frontend** — React SPA in `tailor_studio/web/src/`:
- React 19 + React Router + TanStack Query + Tailwind + Lucide.
- `@` alias resolves to `tailor_studio/web/src/`.
- Pages under `pages/admin/` (Dashboard, Profiles, ProfileDetail,
  BatchDetail, Calendar, Search) plus `Login` / `Signup`.

## Data flow

User pastes URLs → `api.py:api_create_batch` creates `Batch` + `JobUrl`
rows in `pending` → `pipeline.enqueue(job_url_id)` submits to the executor
→ worker runs `_run_single`: scrape (cached), JD-analyze (cached), build
coverage map, propose adjacencies (cached), bullet-rewrite per bullet
(cached + prompt-cached), assemble `.docx` → status updates land in SQLite
→ frontend polls every 3 s.

## Job statuses

`pending` → `fetching` → `analyzing` → `tailoring` → `done`. Off-path
terminals: `needs_manual_jd` (scraper returned <200 chars), `error`.

## Application-funnel statuses (orthogonal)

`not_yet` (default) · `applied` · `error` · `not_remote`.

## Key patterns

- **Per-profile prompt override**: `Profile.tailor_prompt` overrides
  `TAILOR_SYSTEM` when set.
- **Resume structure detection** uses Claude Haiku, cached by `.docx` SHA-256.
- **Output XML parsing**: tailoring prompt uses XML, output is regex-parsed.
  `_repair_output()` patches missing sections from the original so partial
  responses don't fail the whole job.
- `set_paragraph_text()` preserves run-level `.docx` formatting; for runs
  mixed bold/plain it defaults to plain to avoid the "bold bullets" bug.
- **Batches auto-merge**: same-day pastes for the same profile go into one
  batch (Pacific time boundary).
- **Duplicate URLs** already in the system for a profile are silently
  skipped (regardless of status).
- **DB migrations** are hand-rolled inline in `tailor_studio/db.py:init_db()`.
- **All Claude calls are cached** on disk under `data/{jd_spec,adjacency,
  bullet_rewrite,tailor,scrape}_cache/`. Re-running the same `(JD, profile)`
  is free.

## Environment variables

See `.env.sample`. Required: `ANTHROPIC_API_KEY`, `SESSION_SECRET`. Useful
overrides: `TAILOR_MODEL` (Sonnet 4.6), `EXTRACT_MODEL` (Haiku 4.5),
`STUDIO_WORKERS` (concurrent tailorings, default 4), `MAX_URLS_PER_BATCH`
(default 200).
