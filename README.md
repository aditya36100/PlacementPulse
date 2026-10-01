# PlacementPulse

A personal tool that monitors college placement Telegram groups, uses Gemini to extract
structured hiring details from each message, and shows them on a live dashboard with
eligibility checking and AI-generated prep plans.



## How it works

Telegram group messages
│
▼
app/telegram_client.py — Telethon listens for new messages + runs a rolling backfill
│
▼
app/extractor.py — local keyword pre-filter, then Gemini classifies + extracts
│ structured fields (see schema below)
▼
app/db.py — SQLite storage (placements.db), per-group backfill pointers,
│ 7-day rolling retention/purge
▼
app/main.py — FastAPI app, serves static/index.html and GET /api/placements
│ (+ POST /api/placements/{id}/prep for on-demand prep plans)
▼
static/index.html — single-file dashboard (vanilla JS/CSS, no build step).
Inbox-style layout: list + detail pane, filters (type,
location, package, date), "Am I eligible?" profile checker,
saved/reminder toggles, on-demand AI prep plans per listing


## Key files

| File | Responsibility |
|---|---|
| `app/telegram_client.py` | Connects to Telegram (Telethon), listens for live messages, runs `backfill()` on startup to catch up on missed messages within the retention window. Tracks `last_message_id` per group so it never re-scans old messages — but never advances past a message that failed extraction, so failures are retried automatically on the next run. |
| `app/extractor.py` | `extract_placement_info(text, message_date)` — local keyword filter runs first (zero Gemini cost for obviously irrelevant messages), then one Gemini call per message returns structured JSON (see schema below). Handles daily quota exhaustion and temporary rate limits with backoff/retry. |
| `app/researcher.py` | `research_prep(row)` — on-demand, user-triggered Gemini call (with Google Search when available) that researches a specific role/company and returns a detailed prep plan (exact tech stack, prioritized prerequisites, likely interview rounds, tips). Only runs when the user clicks "Generate prep plan" in the UI — not run automatically per message, to conserve quota. |
| `app/db.py` | SQLite helpers: `insert_placement`, `get_all_placements`, `get_placement`, `save_prep_plan`, backfill pointer state (`get_backfill_state` / `set_last_backfill_id`), and `purge_old_data` (deletes anything older than `RETENTION_DAYS`). `init_db()` auto-upgrades the schema with `ALTER TABLE` if older columns are missing, so existing databases don't need to be deleted when the schema grows. |
| `app/main.py` | FastAPI app. Serves `static/index.html` at `/`, `GET /api/placements` (returns all rows from `get_all_placements()` as JSON), and `POST /api/placements/{id}/prep` (triggers `research_prep` and saves the result). |
| `static/index.html` | The entire frontend in one file — no npm/build step. Fetches `/api/placements` on load and polls every 60s. All filtering, the eligibility checker, and prep-plan rendering happen client-side in plain JS. |

## Extracted data schema (per placement)

Each Telegram message that passes the local filter and is judged relevant by Gemini is stored with:

- `company`, `roles`, `summary`, `ctc`, `deadline` (free text), `mode`
- `eligibility` (array of short bullet strings)
- `eligibility_branches` (array, or null = any branch), `eligibility_batch`
- `eligibility_min_cgpa`, `eligibility_min_10`, `eligibility_min_12` (numeric; a bare "X% throughout" with no Class 10/12 specified is converted to a CGPA estimate as X/9.5)
- `eligibility_backlogs` (`"no_active_backlogs_required"` or null)
- `package_lpa` (numeric estimate in LPA; monthly stipends are annualized)
- `deadline_date` (resolved to `YYYY-MM-DD` when determinable)
- `location` (top 1–2 cities)
- `position_type` (`"Internship"` / `"Full-Time"` / `"Other"` — interview schedules, shortlists, and assessment announcements are `"Other"`)
- `has_ppo` (boolean)
- `tech_stack` (stated if given, otherwise inferred from the role; `tech_stack_inferred` flags which)
- `prep_topics` (comma-separated prep areas, Gemini's first pass)
- `prep_plan` (JSON, filled in only after the user clicks "Generate prep plan" — the detailed researched version)
- `raw_message` (original Telegram text, always preserved and shown in the dashboard)

## Environment variables (`.env`, never committed)
GEMINI_API_KEY=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_GROUP= # comma-separated group usernames or numeric chat IDs
TELEGRAM_SESSION_NAME= # defaults to "placement_session"
EXTRACTION_MODEL= # defaults to gemini-3.5-flash-lite
RESEARCH_MODEL= # optional, defaults to EXTRACTION_MODEL — used for prep plans
RETENTION_DAYS=7 # rolling window for backfill + purge
BACKFILL_LIMIT=200 # max messages scanned per group per backfill run
DB_PATH= # optional, defaults to placements.db

## Running it

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app
```

Open http://127.0.0.1:8000 — hard-refresh (Ctrl+F5) after any frontend change, since the
browser can cache the page.

First run (or after deleting `placements.db`) does a full backfill of the last
`RETENTION_DAYS` days of messages, which takes a few minutes due to the Gemini free-tier
rate limit (~1 request per 4.5s). Subsequent runs only process new messages.

## Notes / known quirks

- Only one instance should run at a time against the same `placements.db` — a second
  instance can cause `database is locked` errors. `app/db.py` has a simple instance lock
  (`.app.lock`) for this.
- If Gemini's daily free-tier quota is exhausted mid-run, extraction stops for the rest of
  that run and resumes automatically next time the app starts (failed messages are never
  skipped — see `telegram_client.py`'s `stopped_early` handling).
- Git: `.env`, `*.session*`, `placements.db`, `.venv/`, `.app.lock` are all in `.gitignore`
  and must never be committed. Verify with `git ls-files` before pushing.