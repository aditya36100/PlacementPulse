import os
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, events

from app.extractor import extract_placement_info
from app.db import (
    get_backfill_state,
    get_last_backfill_id,
    insert_placement,
    mark_message_processed,
    message_processed,
    purge_old_data,
    set_last_backfill_id,
)


API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

GROUPS = [
    g.strip()
    for g in os.environ["TELEGRAM_GROUP"].split(",")
    if g.strip()
]

GROUPS = [
    int(g) if g.lstrip("-").isdigit() else g
    for g in GROUPS
]

SESSION_NAME = os.environ.get(
    "TELEGRAM_SESSION_NAME",
    "placement_session",
)

BACKFILL_LIMIT = int(
    os.environ.get("BACKFILL_LIMIT", "200")
)

RETENTION_DAYS = int(
    os.environ.get("RETENTION_DAYS", "7")
)

client = TelegramClient(
    SESSION_NAME,
    API_ID,
    API_HASH,
)


async def _store_if_relevant(message_id, date, text):
    # Don't send the same Telegram message to Gemini again
    if message_processed(message_id):
        print(f"[=] already processed: {message_id}")
        return True  # already finished, safe to advance past

    info = await extract_placement_info(text, message_date=str(date))

    # Only mark the message as processed after Gemini returns a result.
    # If Gemini fails, we'll be able to retry it later.
    if info is None:
        print(f"[!] extraction failed, will retry later: {message_id}")
        return False  # NOT finished — must not advance last_id past this

    if info.get("is_relevant"):
        insert_placement(
            message_id=message_id,
            date=str(date),
            company=info.get("company"),
            roles=info.get("roles"),
            eligibility=info.get("eligibility"),
            ctc=info.get("ctc"),
            deadline=info.get("deadline"),
            mode=info.get("mode"),
            summary=info.get("summary"),
            raw_message=text,
            eligibility_branches=info.get("eligibility_branches"),
            eligibility_batch=info.get("eligibility_batch"),
            eligibility_min_cgpa=info.get("eligibility_min_cgpa"),
            eligibility_min_10=info.get("eligibility_min_10"),
            eligibility_min_12=info.get("eligibility_min_12"),
            eligibility_backlogs=info.get("eligibility_backlogs"),
            package_lpa=info.get("package_lpa"),
            deadline_date=info.get("deadline_date"),
            location=info.get("location"),
            position_type=info.get("type"),
            has_ppo=info.get("has_ppo"),
            tech_stack=info.get("tech_stack"),
            tech_stack_inferred=info.get("tech_stack_inferred"),
            prep_topics=info.get("prep_topics"),
        )

        print(
            f"[+] stored: {info.get('company')} ({info.get('type')}) - "
            f"{info.get('summary')}"
        )
    else:
        print("[-] skipped irrelevant message")

    # Remember that this message has already been analyzed
    mark_message_processed(message_id)
    return True


async def handle_new_message(event):
    text = event.raw_text

    if not text or len(text.strip()) < 10:
        return

    await _store_if_relevant(
        event.id,
        event.date,
        text,
    )


async def backfill():
    """Fetch messages from the rolling 1-week window, resume from last saved ID.

    - First run  : fetches all messages up to RETENTION_DAYS days old.
    - Subsequent : resumes from the last processed message ID (only new msgs).
    - Always     : skips messages older than the rolling cutoff.
    - After done : purges DB rows that have fallen outside the retention window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    for group in GROUPS:
        state = get_backfill_state(group)
        last_id = int(state["last_message_id"] or 0)

        print(
            f"[backfill] group={group} | last_id={last_id} | "
            f"cutoff={cutoff.date()} (rolling {RETENTION_DAYS}d)"
        )

        if last_id > 0:
            messages = client.iter_messages(
                group,
                limit=BACKFILL_LIMIT,
                min_id=last_id,
            )
        else:
            messages = client.iter_messages(
                group,
                limit=None,
                offset_date=None,
            )

        last_seen_id = last_id
        last_seen_message = None
        stopped_early = False
        async for message in messages:
            if message.date is not None:
                msg_date = message.date
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                if msg_date < cutoff:
                    if last_id == 0:
                        break
                    continue

            ok = True
            if message.raw_text:
                ok = await _store_if_relevant(
                    message.id,
                    message.date,
                    message.raw_text,
                )

            if not ok:
                stopped_early = True
                break

            if message.id > last_seen_id:
                last_seen_id = message.id
                last_seen_message = message

        if last_seen_id > last_id:
            set_last_backfill_id(
                group,
                last_seen_id,
                last_message_date=(
                    str(last_seen_message.date)
                    if last_seen_message is not None
                    else None
                ),
            )
            print(f"[backfill] {group}: saved last_id={last_seen_id}")
        else:
            print(f"[backfill] {group}: no new messages found")

        if stopped_early:
            print(
                f"[backfill] {group}: stopped early after a failed "
                f"extraction — remaining messages will be retried next run"
            )

    purge_old_data(retention_days=RETENTION_DAYS)
    print("Backfill complete.")



async def start_listener(run_backfill: bool = True):
    await client.start()  # type: ignore

    print("Telegram client connected.")

    if run_backfill:
        await backfill()

    client.add_event_handler(
        handle_new_message,
        events.NewMessage(chats=GROUPS),
    )

    print(
        f"Listening for new messages in {GROUPS} ..."
    )

    await client.run_until_disconnected()