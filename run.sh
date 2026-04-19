#!/usr/bin/env bash
# Start the resume-maker web app in dev mode.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env — copy .env.sample to .env and fill in values first."
  exit 1
fi

exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
