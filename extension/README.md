# Tailor Studio — Sourcing extension (user-side)

For the person who **collects URLs and queues tailoring jobs**. No applying happens through this extension.

## Install

1. `chrome://extensions` → enable Developer Mode (top-right)
2. Click **Load unpacked** → point at this folder (`extension/`)
3. Pin the icon to the toolbar

## Features

- **Add button (per page)**: a small floating **✦** appears on every page. Open a job, read the JD, click it → pick a profile → **Add this job** sends just that URL into the tailoring system. Manual and one-at-a-time, so no duplicates and no EasyApply spam — you only add what you've actually reviewed. (Requires being logged in to the web app in the same browser.)
- **Quick Add (bulk)**: open many job tabs across windows → click the toolbar icon → tick which open tabs to queue and which profiles to send them to → one click creates per-profile batches and (optionally) closes the source tabs.
- **Rescue Mode** (silent): when a JD on an ATS host is stuck in `needs_manual_jd`, opening it in your browser sends the rendered DOM to the server so Haiku can re-extract. The stuck row auto-heals into `pending` and re-runs the pipeline.

## Companion extension

The apply-side helpers — Resume Ready widget, Fill Form, upload audit — live in the separate **Tailor Studio — Co-worker** extension under `extension-coworker/`. Install that on the co-worker's browser only.
