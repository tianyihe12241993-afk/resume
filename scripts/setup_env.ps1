# Sets up the Python virtual environment for tailor_studio.
#
# Why this script exists: python-jobspy (used by the job-discovery feature)
# over-pins numpy==1.26.3 / pandas<3.0, neither of which has a Windows wheel for
# Python 3.14 (they'd compile from source and fail without a C compiler). Modern
# numpy/pandas DO ship 3.14 wheels and jobspy runs fine against them, so we
# install jobspy with --no-deps and let requirements.txt provide compatible
# numpy/pandas + jobspy's other runtime deps. Also installs the Playwright
# Chromium browser used by the JD scraper's SPA fallback.
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
# jobspy itself: skip its (broken-on-3.14) pins; deps already satisfied above.
& $py -m pip install --no-deps python-jobspy
# Playwright browser for the JD scraper's SPA-rendering fallback.
& $py -m playwright install chromium

Write-Host "`nVerifying imports ..."
& $py -c "import jobspy, apscheduler, playwright, pandas, numpy; import tailor_studio.main; print('OK: tailor_studio imports; jobspy + apscheduler + playwright present')"
Write-Host "Done. Run the backend with:"
Write-Host "  .\.venv\Scripts\python -m uvicorn tailor_studio.main:app --reload --port 8001"
