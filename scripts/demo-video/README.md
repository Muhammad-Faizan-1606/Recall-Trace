# Demo walkthrough video (and end-to-end check)

These scripts drive a real browser through every RecallTrace section and operation, check each
step against the server's response, and record a narrated walkthrough video with chapters.
Without recording (`FAST=1`) the same run is a quick end-to-end check of the whole product.

Everything runs on a separate local demo database, seeded with the fictional companies
**Harbourline Foods (demo)** (recall) and **Lahore Knit Mills (demo)** (factory). All contacts are
`.test` addresses and customer notices are written to a local mailbox (`MAIL_MODE=local`), so
nothing is ever emailed. Never point these scripts at a shared or production database.

## What it covers (28 chapters, 221 checked steps)

1. **Recall side:** sign-in and navigation, catalog, master data, operations (purchase → receipt
   → transfer → production → sale → shipment), quality (template, inspection, issue, hold, and a
   refused transfer of held stock), evidence uploads, CSV import and export, roles, invitations,
   the audit log and job-role preview.
2. **Full recall lifecycle with two people:** an invited reviewer sets up two-factor sign-in
   (the setup key is blurred on screen). The owner then investigates, traces the lot and submits.
   The reviewer approves and verifies. The notice is drafted, approved, delivered locally and
   acknowledged, recovery is recorded, and the case is closed.
3. **Factory Suite:**
   - home tiles, job-role preview and the 3D map with bundle drag-and-drop
   - alerts and clients (logo upload)
   - styles and operation bulletins, production orders and the planning board
   - line balancing, machines and the shop floor (output, stops, quality, corrections)
   - batch cards (rolls → dye batch → bundles → tickets → scan → sewn)
   - maintenance, factory setup, and the yarn-to-carton trace

A step passes only when the server accepted the action: no error flash or form error, no HTTP
error status and no browser error. Many steps also check the expected result on the page.

## Requirements

- The repository's Python environment (`.venv`) and a `.env` with `DATABASE_URL`.
- Local PostgreSQL where an admin login can create databases (default: socket `/tmp`, user
  `postgres`; override with `PGADMIN_HOST` and `PGADMIN_USER`), and Redis on `127.0.0.1:6379`.
- Node.js and Playwright 1.63 (`npm install` here, then `npx playwright install chromium` if the
  machine has no browser yet).
- `ffmpeg`, only for assembling the video.

## Run it

```bash
./reset.sh
```

`reset.sh` creates the demo database (`recalltrace_video`, override with `DEMO_DB`), seeds it, and
writes `demo.env.sh` with the database URL and fresh random passwords for the two demo accounts.
That file is ignored by git.

In a second terminal:

```bash
./serve.sh
```

Then either check everything quickly without video:

```bash
FAST=1 ./run.sh
```

or record the walkthrough, then join the chapters and write the test report:

```bash
./run.sh
```

```bash
./assemble.sh && node report.js
```

The output goes to `out/`:

- `RecallTrace-full-walkthrough.mp4`: intro, 28 chapters and a results card, with chapter markers.
- `RecallTrace-walkthrough-test-report.md`: every chapter with its start time in the video, and
  every step with its result.
- `results.json`: the raw step results.

The chapters depend on each other, so run `./reset.sh` before each full run.

## Editing the script

- `kit.js`: the toolkit. Captions, visible cursor, title cards, per-chapter video, form helpers
  that open collapsed sections, error detection, authenticator codes, the report.
- `demo.js`: the chapter list. `ch_core.js`, `ch_ops.js`, `ch_quality.js`, `ch_recall.js` and
  `ch_factory.js` hold the chapters themselves.
- To work on one chapter, run the chapters before it once and save a snapshot. Then reload the
  snapshot and run only the chapter you are editing:

```bash
FAST=1 ./run.sh 1 2 3 4 5 6 7 8
```

```bash
./snap.sh save ch8
```

```bash
./snap.sh load ch8
```

```bash
FAST=1 DUMP=1 ./run.sh 9
```

  `DUMP=1` prints the forms on the page whenever a step fails, which makes fixing a selector quick.
- `fixtures/` holds the fictional test files: an inspection photo, an item CSV and a client logo.
