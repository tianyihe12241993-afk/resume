# Tailor Studio — Sourcing extension (user-side)

For the person who **collects URLs and queues tailoring jobs**. No applying happens through this extension.

## Install

1. `chrome://extensions` → enable Developer Mode (top-right)
2. Click **Load unpacked** → point at this folder (`extension/`)
3. Pin the icon to the toolbar

## Features

- **Quick Add**: open many job tabs across windows → click extension → tick which open tabs to queue and which profiles to send them to → one click creates per-profile batches and (optionally) closes the source tabs.
- **Rescue Mode** (silent): when a JD on an ATS host is stuck in `needs_manual_jd`, opening it in your browser sends the rendered DOM to the server so Haiku can re-extract. The stuck row auto-heals into `pending` and re-runs the pipeline.

## Companion extension

The apply-side helpers — Resume Ready widget, Fill Form, upload audit — live in the separate **Tailor Studio — Co-worker** extension under `extension-coworker/`. Install that on the co-worker's browser only.
