# Tailor Studio — browser extension (all-in-one)

One extension for the whole loop: **source** jobs into the tailoring system, then
**apply** with the tailored resume. (This replaces the two former extensions —
"Sourcing" and "Co-worker" — which are now merged here.)

## Install

1. `chrome://extensions` → enable Developer Mode (top-right)
2. **Load unpacked** → point at this folder (`extension/`)
3. Pin the icon to the toolbar
4. Make sure you're **logged in** to the web app (http://127.0.0.1:8001) in the same browser — the extension uses your session.
5. Open the popup → pick a **Main profile** (used by the on-page resume widget + Draft).

## Source features (collect & queue jobs)

- **Add button (per page)**: a floating **✦** at the top-right of every page. Open a job, read the JD, click it → pick a profile → **Add this job** sends just that URL into tailoring. Manual and one-at-a-time, so no duplicates and no EasyApply spam — you only add what you've reviewed.
- **Quick Add (bulk)**: open many job tabs → click the toolbar icon → tick which tabs + which profile(s) → one click queues them all and (optionally) closes the tabs.

## Apply features (use the tailored resume)

- **Resume Ready widget**: on a job page, the bottom-right widget auto-downloads the tailored `.docx` for your Main profile and shows the exact filename.
- **✨ Draft**: bottom-left button — drafts answers for required essay/screener questions using the candidate profile + JD + answer library. You review before submitting.
- **Upload audit**: when you attach a file in the application form, it's hashed and checked against the tailored/base resume; the studio UI shows ✓ Tailored / ⚠ Base / ✕ Other.

## Shared

- **Rescue Mode** (silent): if a JD page was stuck in `needs_manual_jd`, opening it sends the rendered DOM so the server re-extracts the JD and the row auto-heals.
- **Server URL**: the "Server URL…" link in the popup overrides `http://127.0.0.1:8001` (e.g. a tunneled URL).

## Answer library

The standard answers used by Draft live per-profile in the studio web UI under **Answers**. The extension reads the library of the Main profile picked in the popup.

## Files

`manifest.json` · `background.js` (service worker) · `add_button.js` (floating Add,
all pages) · `apply.js` (resume widget + draft + upload audit + rescue, ATS hosts)
· `formfill.js` (standard-field fill helpers) · `popup.html` / `popup.js`.
