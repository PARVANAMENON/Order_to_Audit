# Order-to-Audit — automated demo video

Caption-narrated, single-take product demo recorded with Playwright against the
running Django app. Captions and title cards carry the narration on screen; an
optional generated voice-over track can be muxed on top of the same recording.

## Deliverables

| File | Description |
|---|---|
| `demo/order-to-audit-demo.mp4` | Silent H.264 video, 1280×720, **8:10** (490.3 s) |
| `demo/order-to-audit-demo-voiced.mp4` | Same video with the optional narration track (AAC 48 kHz) |
| `demo/videos/order-to-audit-demo.webm` | Original Playwright recording (VP8) |
| `demo/screens/NN-*.png` | Screenshot captured at the end of every scene |
| `demo/screens/04-invoice-pdf.png` | The GST invoice PDF, cropped to its line items |
| `demo/downloads/` | Artifacts downloaded during the run (invoice PDF, sales-register CSV) |
| `demo/run-summary.json` | Per-scene success/failure, start time, duration and demo facts |
| `demo/captions.json` | Every caption with the time it appeared, used to sync the voice-over |
| `demo/narration.json` | Voice-over script, anchored to captions or scene offsets |
| `demo/voiceover.py` | Renders the narration with `edge-tts` and muxes it onto the MP4 |

## Prerequisites

- Node.js 18+ and the app running at `http://127.0.0.1:8000` with seeded data:
  ```bash
  python backend/manage.py migrate
  python backend/manage.py seed_benchmark
  python backend/manage.py runserver
  ```
- Playwright + Chromium:
  ```bash
  cd demo && npm install && npx playwright install chromium && cd ..
  ```
- Optional voice-over: `python -m pip install edge-tts` (see below).
- `ffmpeg` / `ffprobe` (duration check + MP4 conversion) and Poppler
  `pdftoppm` (renders invoice page 1 to PNG). The script auto-detects winget
  installs on Windows and also accepts `FFMPEG`, `FFPROBE` and `PDFTOPPM`
  environment variables pointing at the executables.

## Re-run

From the project root:

```bash
node demo/record.mjs
```

Before the browser opens, the script runs the dedicated demo seed profile:

```bash
python backend/manage.py seed_benchmark --profile demo
```

That profile deletes every transactional document — orders, invoices,
dispatches, credit notes, payments, production runs, purchases, stock movements,
adjustments, overheads and the audit trail — and then reseeds the masters,
opening stock, BOM, demo purchase, demo run and demo orders. Masters, users,
customers, suppliers and the BOM are preserved. The result is the same clean
baseline (206 packets of finished goods, one paid invoice, one pending order)
every time. Record the current data without resetting it with:

```bash
SKIP_SEED=1 node demo/record.mjs
```

Override the target:

```bash
TARGET=http://192.168.1.20:8000 node demo/record.mjs
```

Convert the fresh WebM to MP4:

```bash
ffmpeg -y -i demo/videos/order-to-audit-demo.webm \
  -c:v libx264 -pix_fmt yuv420p -crf 23 -preset veryfast \
  demo/order-to-audit-demo.mp4
```

The script resets `demo/videos`, `demo/screens` and `demo/downloads`. Application
data is reset by the `--profile demo` seed unless `SKIP_SEED=1` is set; after
that it only creates new orders, invoices, a dispatch, a payment and a
production run through the UI. Stock figures in the narration are read from the
order page, so repeated runs stay accurate as stock changes.

## Voice-over (optional)

```bash
python -m pip install edge-tts
python demo/voiceover.py
```

This writes `demo/order-to-audit-demo-voiced.mp4`; the silent MP4 is left
untouched. Lines live in `demo/narration.json` and are anchored to the caption
that should be on screen when they start (or to a scene offset), using the
timings recorded in `captions.json`. If a line would overlap the previous one it
is delayed just enough to stay clear, and the run reports the delay. Useful
options:

```bash
python demo/voiceover.py --plan       # show anchors without generating audio
python demo/voiceover.py --no-mux     # synthesise and check only
python demo/voiceover.py --voice en-GB-RyanNeural --rate +12%
```

Synthesised clips are cached in `demo/audio/segments/` by text hash, so changing
one line only re-renders that line.

## Scenes

| # | Scene | Budget | What happens |
|---|---|---|---|
| 01 | Title | 0:40 | Title card, the factory problem, login page |
| 02 | Salesman | 1:20 | Login as `salesmanA`, 5,000-packet order for Retailer A (stock-shortage hint), offline PWA order while `context.setOffline(true)`, queue badge, reconnect and sync |
| 03 | Masters | 1:00 | Items, HSN/GST/tolerance, unit conversions, customers and GST state split; Murukku 200 g BOM context |
| 04 | Admin | 1:15 | Login as `admin`, approve with quantity trimmed to 200 against stock, create gapless GST invoice (CGST+SGST), download and show the PDF zoomed to its line items, post dispatch, record a FIFO payment, show the credit-note flow |
| 05 | Production | 1:15 | Login as `production`, create a run from the BOM, enter output/wastage/damaged packaging and per-line actuals, post to the ledger, show variance flags |
| 06 | Accountant | 1:00 | Login as `auditor`, run costing (WAC, cost/packet, margin), sales register + CSV export, GST summary, stock ledger, outstanding ageing |
| 07 | Owner | 1:00 | Login as `owner`, dashboard KPIs and low-stock alerts, append-only audit trail, immutable posted invoice, ledger-derived stock |
| 08 | Closing | 0:30 | Stack and role summary card |

Total scene budget: 480 s. Measured WebM/MP4 duration: **490.3 s** (8:10).

## Notes and intentional skips

- **Offline ordering is real** and is demonstrated: service worker ready, network
  disabled, order queued in `localStorage`, network restored, queue synced through
  the idempotent API.
- **Credit note**: the flow is shown on the invoice screen (reason entered), but
  not submitted, so the demo does not reverse the invoice it just created.
- **PDF**: the invoice link is served `inline`, so Playwright still emits a
  download event; the script saves the PDF, renders page 1 at 200 DPI with
  `pdftoppm`, trims the blank lower two-thirds of the A4 page in a canvas and
  displays the cropped page full-width, so the HSN, quantity, rate and tax
  columns are readable.
- **Skipped beats (feature not present in this app):**
  - No language switcher / Tamil UI toggle.
  - No “Leakage Radar”, “Loop Closer” or “Benchmark Console” screens.
  - No standalone BOM screen; the BOM is shown through masters and the
    production run's planned lines.
- All navigation uses one browser context and one page; roles are switched with
  the app's own Logout/Login buttons, so the video is a single continuous take.
- Every scene is isolated in `try/catch`: a failure logs, saves
  `NN-*-failure.png`, returns to the landing page and continues.
