# Sets up the Python virtual environment for tailor_studio and installs the
# Playwright Chromium browser used by the JD scraper's SPA-rendering fallback.
#
# Usage (from the project root):  .\scripts\setup_env.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
# Playwright browser for the JD scraper's SPA-rendering fallback.
& $py -m playwright install chromium

Write-Host "`nVerifying imports ..."
& $py -c "import playwright; import tailor_studio.main; print('OK: tailor_studio imports; playwright present')"
Write-Host "Done. Run the backend with:"
Write-Host "  .\.venv\Scripts\python -m uvicorn tailor_studio.main:app --reload --port 8001"
