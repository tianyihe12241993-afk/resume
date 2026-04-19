# Running on Windows

Tested with Python 3.12 on Windows 11.

## Prerequisites

- **Python 3.12+** — install from https://www.python.org/downloads/windows/.
  Make sure to tick "Add python.exe to PATH" in the installer.
- **Git** (optional, only if you want to clone the repo).

## Setup

Open **PowerShell** (or Command Prompt) in the project folder, then:

```powershell
# Create a virtual environment
py -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1
# (If PowerShell blocks the script, run:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned)
# In Command Prompt instead:
#   .venv\Scripts\activate.bat

pip install -r requirements.txt

# Make a config file
copy .env.sample .env
notepad .env
```

In `.env`, fill in:
- `ANTHROPIC_API_KEY`
- `SESSION_SECRET` (any long random string)
- `ADMIN_EMAIL`
- `APP_BASE_URL` (leave as `http://127.0.0.1:8000` for local; change to your ngrok URL when tunneling)

## Run the server

```powershell
.\run.bat
```

…or directly:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in your browser. On first boot the admin gets a setup URL printed in the console — open it to set the password.

## Optional: expose to the internet with ngrok

1. Install ngrok: https://ngrok.com/download (or `winget install ngrok`).
2. Sign up for a free account, then in PowerShell:
   ```powershell
   ngrok config add-authtoken YOUR_AUTHTOKEN
   ```
3. With the server running, in a separate PowerShell window:
   ```powershell
   ngrok http 8000
   ```
4. Copy the `https://...ngrok-free.dev` URL ngrok prints, paste it into `.env` as `APP_BASE_URL`, and restart the server. Now invite links emitted by the app will use the public URL.

## Auto-start on Windows boot (optional)

Easiest path is **Task Scheduler**:

1. Open Task Scheduler → Create Task.
2. **General** tab: name it "resume-maker"; check "Run whether user is logged on or not".
3. **Triggers** tab: New → "At startup".
4. **Actions** tab: New →
   - Program/script: `cmd.exe`
   - Add arguments: `/c "C:\path\to\resume_maker\run.bat"`
   - Start in: `C:\path\to\resume_maker`
5. Save. Reboot to verify.

Pair it with a second task that starts ngrok if you want the public URL up too.

## Things that will not differ from macOS

- SQLite database, base resume files, and tailored docx all live in `.\data\`.
- Magic-link / password setup, batch processing, dedupe, etc. all behave the same.
- US Pacific time display works (we ship `tzdata` so Windows has timezone data).

## Things to watch out for

- Antivirus may quarantine the SQLite write — exclude the `data\` folder if you see weird "permission denied" errors.
- If you change Python versions, recreate the venv (`rmdir /s .venv` then re-run setup).
- Word/LibreOffice are not required (we removed PDF conversion).
