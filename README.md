# resume-maker

A web platform for generating job-tailored `.docx` resumes at scale. Paste job URLs, the system scrapes the JD, tailors the resume via Claude, and produces a downloadable `.docx`.

## Quick Start (clone and run)

```bash
git clone https://github.com/tianyihe12241993-afk/resume.git
cd resume

# 1. Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
# Edit .env — set ANTHROPIC_API_KEY, SESSION_SECRET, ADMIN_EMAIL
./run.sh
# Backend runs on http://127.0.0.1:8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev
# Frontend runs on http://127.0.0.1:5173
```

The repo includes the SQLite database (`data/app.db`) and base resume `.docx` files so you can clone to another machine and pick up where you left off. Generated outputs are not tracked (713MB+) — retry batches to regenerate them.

### First login

The `ADMIN_EMAIL` in `.env` is auto-promoted to admin on boot. If that account has no password yet, an invite URL prints to the server console. Open it to set your password.

### Expose to internet (free)

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

This gives you a random `https://xxx.trycloudflare.com` URL (changes each restart). Update `APP_BASE_URL` in `.env` to match so invite links work.

## Roles

| Role | Can do |
|---|---|
| **Admin** | Create profiles, upload base `.docx`, grant bidder access, paste URLs into batches, paste JD manually when scraping fails |
| **Bidder** | Log in, see granted profiles, download tailored `.docx` files per batch |

## Admin flow (daily)

1. `/admin` → click a profile or create one.
2. Upload the profile's base `.docx`.
3. Grant access: add a bidder's email (account auto-created, invite link generated).
4. "New batch": paste one URL per line, submit.
5. The batch page auto-refreshes:
   - `pending/fetching/tailoring` — in progress
   - `done` — docx ready (download inline)
   - `needs_manual_jd` — scraper couldn't get enough text; paste JD manually
   - `error` — click retry

## Bidder flow

1. Log in with the email the admin added → set password via invite link.
2. `/my` shows only profiles you have access to.
3. Click a profile → batches by date → download tailored `.docx` files.

## Tailoring rules

- **Never invents** tech, companies, projects, metrics, titles, or dates.
- **Never adds or drops bullets** — rewording and reordering only.
- Rewrites the Summary (3–5 sentences) to front-load JD-relevant experience.
- Reorders bullets within each job so the most JD-relevant one appears first.
- Reorders skill categories to prioritize what the JD cares about.
- May add a few adjacent skill keywords the JD emphasizes (capped, must be plausible).

The full prompt is in `app/tailoring.py` → `TAILOR_SYSTEM`. Each profile can override it.

## Supported Job Boards

Ashby, Lever, Greenhouse, Workday, SmartRecruiters, Rippling, Workable, Oracle HCM, plus JSON-LD fallback and generic HTML extraction.

## Environment Variables

See `.env.sample`. Required:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `SESSION_SECRET` | Random string for signing session cookies |
| `ADMIN_EMAIL` | Email promoted to admin on boot |

Optional: `TAILOR_MODEL`, `EXTRACT_MODEL`, `APP_BASE_URL`, `SMTP_HOST`/`SMTP_USER`/`SMTP_PASS` (for emailing invite links instead of printing to console).

## Deployment

- **Local + tunnel**: `./run.sh` + `cloudflared tunnel --url http://localhost:8000`
- **Fly.io**: Dockerfile with Python 3.12, mount `/data` on a persistent volume, set env vars in `fly secrets`
- **Any VPS**: `uvicorn app.main:app --host 0.0.0.0 --port 8000` behind nginx

SQLite is fine for a handful of profiles and several hundred batches.
