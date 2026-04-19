@echo off
REM Start the resume-maker web app in dev mode (Windows).
cd /d "%~dp0"

if not exist .env (
  echo No .env -- copy .env.sample to .env and fill in values first.
  exit /b 1
)

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
