# Tailor Studio — Co-worker extension (apply-side)

For the person who **opens job URLs and applies**. Does not source / queue / tailor.

## Install

1. `chrome://extensions` → enable Developer Mode (top-right)
2. Click **Load unpacked** → point at this folder (`extension-coworker/`)
3. Pin the icon to the toolbar
4. Open the popup → pick the **main profile** (which determines which tailored resume + which answer library gets used)
5. (Optional) Server URL button if you're using a tunneled URL instead of `http://127.0.0.1:8001`.

## Features

- **Resume Ready widget**: open any job page → corner widget auto-downloads the tailored `.docx` for the main profile and shows you the exact filename you'll find in `~/Downloads`.
- **Fill Form**: open the popup → click 📝 Fill form → standard fields (name, email, phone, LinkedIn, current company, eligibility yes/no, etc.) get filled into the form. Field signals are matched by label / name / id / placeholder. React-aware. Co-worker still reviews and submits.
- **Upload audit**: when you select a file in the form's resume input, the extension hashes it and verifies against the tailored / base resume. The studio UI shows ✓ Tailored / ⚠ Base / ✕ Other for each applied job.
- **Rescue Mode** (silent): if a JD page was stuck in `needs_manual_jd`, opening it sends the rendered DOM to the server so it auto-heals. Same behavior as the user extension — fine to have on both sides.

## Answer library

The standard answers used by Fill Form live per-profile in the studio web UI under **Answers**. Edit them there. The extension reads whichever library belongs to the main profile you picked in the popup.

## Companion extension

The user-side **Tailor Studio — Sourcing** extension under `extension/` handles URL collection and queueing. The two extensions don't depend on each other — install whichever ones you need on each browser.
