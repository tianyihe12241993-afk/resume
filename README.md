# resume-maker

A small web platform for generating job-tailored `.docx` resumes at scale.

## Roles

| Role | Can do |
|---|---|
| **Admin** | Create profiles, upload each profile's base `.docx`, grant access to bidders, paste daily URLs into batches, paste JD manually when scraping fails |
| **Bidder** | Log in, see only the profiles they were granted access to, download tailored `.docx` files per batch |

Every URL goes through: **scrape → tailor with Claude → save .docx**, organized into batches so each day's URL drop stays together.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
# edit .env — set ANTHROPIC_API_KEY, SESSION_SECRET, ADMIN_EMAIL
./run.sh
# → http://127.0.0.1:8000
```

On first boot, the email in `ADMIN_EMAIL` is promoted to the sole admin.

### Logging in (dev mode, no SMTP)

1. Visit `/login`, enter your email, submit.
2. The magic-link URL prints to the **server console** (stdout of `uvicorn`).
3. Paste that URL into the browser → you're in.

In production, set `SMTP_HOST` + `SMTP_USER` + `SMTP_PASS` so magic links are emailed instead.

## Admin flow (daily)

1. `/admin` → click a profile or create one.
2. If new: upload the profile's base `.docx`.
3. Grant access: add the bidder's email. They can then log in with it (same magic-link flow; their account is auto-created on first grant).
4. "New batch": paste one URL per line, submit.
5. The batch page auto-refreshes every 3s:
   - `pending/fetching/tailoring` — in progress
   - `done` — docx ready (download button inline)
   - `needs_manual_jd` — scraper couldn't get enough text. Expand the row, paste the job description, click "Save JD & re-run".
   - `error` — click retry.

## Bidder flow

1. `/login` with the email the admin added → get magic link → click.
2. `/my` shows only the profiles you have access to.
3. Click a profile → see every batch by date → click a batch → download each tailored `.docx`.

## Tailoring rules (enforced in the prompt)

- **Never invents** tech, companies, projects, metrics, titles, or dates.
- **Never adds or drops bullets** — rewording and reordering only.
- **Never changes** job titles, companies, or employment dates.
- Rewrites the Summary (3–5 sentences) to front-load JD-relevant experience.
- Reorders bullets within each job so the most JD-relevant one appears first.
- Reorders skill categories to prioritize the ones the JD cares about.

The full prompt is in `app/tailoring.py` → `TAILOR_SYSTEM`. Tweak it if you want different behavior.

## Layout

```
resume_maker/
├── app/
│   ├── main.py           # FastAPI routes
│   ├── config.py         # env-driven settings
│   ├── db.py             # SQLAlchemy engine + session
│   ├── models.py         # User / Profile / ProfileAccess / Batch / JobUrl
│   ├── auth.py           # magic-link email + signed session cookie
│   ├── scraping.py       # per-board fetchers (Ashby, Lever, Greenhouse, Jobvite, ApplyToJob, generic HTML)
│   ├── tailoring.py      # docx parse / Claude call / docx write
│   ├── pipeline.py       # background thread: fetch → tailor → save
│   ├── storage.py        # file-path helpers
│   └── templates/        # Jinja2 (login, admin, bidder, partials)
├── data/                 # gitignored — SQLite db + uploaded + generated files
├── tailor.py             # legacy standalone CLI (still works)
├── run.sh                # dev launcher
└── requirements.txt
```

## CLI is still there

`tailor.py` is the original single-shot CLI from before the web app. Point it at a jobs.txt file + a .docx and it will generate one folder of outputs. Not used by the web app but kept for ad-hoc runs.

## Deployment

For 24/7 hosting, the easiest path:

- Fly.io: one `Dockerfile` with Python 3.12, mount `/data` on a persistent volume, set env vars in `fly secrets`. ~$0-5/mo for a small VM.
- Any VPS: clone the repo, `pip install -r requirements.txt`, `uvicorn app.main:app --host 0.0.0.0 --port 8000` behind nginx.

SQLite is fine for a handful of profiles + several hundred batches. If you outgrow it, swap to Postgres by changing the engine URL in `app/db.py`.
