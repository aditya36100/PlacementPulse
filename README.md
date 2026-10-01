# Placement Wire

Listens to your college placements Telegram group under your own account, uses Claude to
figure out which messages are actual company announcements (vs. chatter), pulls out company /
role / eligibility / CTC / deadline, and shows the clean list on a small web dashboard you can
open from your phone.

## How it works

- `app/telegram_client.py` logs into Telegram **as you** (not a bot) using Telethon, so it can
  read a group you're already a member of without needing admin permission.
- Every new message is sent to Claude (`app/extractor.py`) with instructions to decide if it's
  a placement announcement and, if so, extract structured fields.
- Relevant ones are saved to a local SQLite database (`app/db.py`).
- `app/main.py` runs a small FastAPI server that serves the dashboard (`static/index.html`) and
  an API endpoint (`/api/placements`) the dashboard polls every 30 seconds.

## 1. Get your Telegram API ID and Hash

This is a one-time step so your account is allowed to run this kind of script:

1. Go to https://my.telegram.org and log in with your phone number.
2. Click **API Development Tools**.
3. Fill in any app name/description (e.g. "Placement Tracker") and submit.
4. You'll get an **api_id** (a number) and an **api_hash** (a long string). Copy both.

## 2. Get an Anthropic API key

Go to https://console.anthropic.com, create a key under **API Keys**. Note: this is a
pay-as-you-go API key, separate from a claude.ai subscription — extraction calls will cost a
small amount per message (using Haiku instead of Sonnet, set in `.env`, cuts this further since
this is a simple classification task).

## 3. Set up the project

```bash
cd placement-tracker
python -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Now open `.env` and fill in:
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` from step 1
- `TELEGRAM_GROUP` — the group's @username if it has one. If it's a private group with no
  username, use its numeric chat ID instead (message anything in the group, forward it to
  [@userinfobot](https://t.me/userinfobot) or use Telethon's `client.get_dialogs()` once to find it — ask me if you get stuck here).
- `ANTHROPIC_API_KEY` from step 2

## 4. Run it locally first

```bash
uvicorn app.main:app --reload
```

The **first time**, Telethon will ask for your phone number and the OTP code Telegram sends
you, right there in the terminal — this is expected, it's logging in as you. After that it
saves a session file (`placement_session.session`) so you won't be asked again.

Once it's running, open **http://localhost:8000** in your browser. It'll backfill the last 200
messages first, then keep listening live.

**Keep this `.session` file private** — anyone with it can access your Telegram account.
Don't commit it to a public GitHub repo (a `.gitignore` is included).

## 5. Make it reachable from your phone, from anywhere

Running on `localhost` only works on the same machine/network. To actually check it from your
phone anywhere, you need to deploy it somewhere that stays running. A few options, easiest first:

**Option A — Railway.app (recommended to start)**
1. Push this folder to a private GitHub repo.
2. Create a new project on [Railway](https://railway.app), deploy from that repo.
3. Add the same variables from your `.env` under the project's **Variables** tab.
4. Add a **volume** mounted at `/app` (or wherever you run it from) so `placements.db` and the
   `.session` file survive restarts — without this, a redeploy wipes your data and logs you out
   of Telegram.
5. Set the start command to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
6. First deploy will need the OTP once — Railway's log/shell view lets you type it in.
7. Railway gives you a public URL — open that on your phone.

**Option B — a cheap VPS (DigitalOcean, Hetzner, etc.)**
More control, persistent disk by default, but you set up Python/systemd yourself. Worth it if
you outgrow Railway's free tier.

**Option C — Replit**
Fastest to get *something* live, but free-tier apps sleep when idle, which means the listener
stops picking up new messages until someone visits — not ideal for something meant to run
continuously in the background.

## Notes and tuning

- `BACKFILL_LIMIT` in `.env` controls how many old messages get scanned on first run.
- Switch `EXTRACTION_MODEL` to `claude-haiku-4-5-20251001` for a cheaper/faster model if Sonnet
  feels like overkill for this — classification of a short Telegram message is well within
  Haiku's ability.
- The dashboard has a search box (filters by company/role) and a "show original message" toggle
  per entry so you can sanity-check what Claude extracted against the real text.
- If you ever want this to also DM you (not just show a dashboard), that's a small addition to
  `telegram_client.py` — just ask.
