import sqlite3
import os
import time
import json
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get("DB_PATH", "placements.db")
INSTANCE_LOCK_PATH = os.environ.get("INSTANCE_LOCK_PATH", os.path.join(os.getcwd(), ".app.lock"))


def acquire_instance_lock(lock_path=None):
    lock_file = lock_path or INSTANCE_LOCK_PATH

    if os.path.exists(lock_file):
        try:
            age = time.time() - os.path.getmtime(lock_file)
        except OSError:
            age = 0

        if age > 30:
            try:
                os.remove(lock_file)
            except OSError:
                pass
        else:
            raise RuntimeError(f"Another app instance is already running using lock: {lock_file}")

    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    return fd


def release_instance_lock(fd):
    if fd is None:
        return

    try:
        os.close(fd)
    except OSError:
        pass

    try:
        os.unlink(INSTANCE_LOCK_PATH)
    except FileNotFoundError:
        pass
    except OSError:
        pass


# Columns added on top of the original simple schema. Each tuple is
# (column_name, SQL type) and is added with ALTER TABLE if missing,
# so existing databases upgrade in place without losing data.
NEW_COLUMNS = [
    ("eligibility_branches", "TEXT"),
    ("eligibility_batch", "TEXT"),
    ("eligibility_min_cgpa", "REAL"),
    ("eligibility_min_10", "REAL"),
    ("eligibility_min_12", "REAL"),
    ("eligibility_backlogs", "TEXT"),
    ("package_lpa", "REAL"),
    ("deadline_date", "TEXT"),
    ("location", "TEXT"),
    ("position_type", "TEXT"),
    ("has_ppo", "INTEGER"),
    ("tech_stack", "TEXT"),
    ("tech_stack_inferred", "INTEGER"),
    ("prep_topics", "TEXT"),
    ("prep_plan", "TEXT"),
    ("application_link", "TEXT"),
]


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS placements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER UNIQUE,
                date TEXT,
                company TEXT,
                roles TEXT,
                eligibility TEXT,
                ctc TEXT,
                deadline TEXT,
                mode TEXT,
                summary TEXT,
                raw_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id INTEGER PRIMARY KEY,
                processed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backfill_state (
                chat_id TEXT PRIMARY KEY,
                last_message_id INTEGER NOT NULL DEFAULT 0,
                last_message_date TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        columns = conn.execute(
            "PRAGMA table_info(backfill_state)"
        ).fetchall()
        column_names = {row[1] for row in columns}
        if "last_message_date" not in column_names:
            conn.execute(
                "ALTER TABLE backfill_state ADD COLUMN last_message_date TEXT"
            )

        # Upgrade placements table with the richer fields the dashboard needs.
        placement_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(placements)").fetchall()
        }
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in placement_columns:
                conn.execute(f"ALTER TABLE placements ADD COLUMN {col_name} {col_type}")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def message_processed(message_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM processed_messages
            WHERE message_id = ?
            LIMIT 1
            """,
            (message_id,),
        ).fetchone()

        return row is not None


def mark_message_processed(message_id):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_messages (message_id)
            VALUES (?)
            """,
            (message_id,),
        )


def placement_exists(message_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM placements
            WHERE message_id = ?
            LIMIT 1
            """,
            (message_id,),
        ).fetchone()

        return row is not None


def insert_placement(
    message_id,
    date,
    company,
    roles,
    eligibility,
    ctc,
    deadline,
    mode,
    summary,
    raw_message,
    eligibility_branches=None,
    eligibility_batch=None,
    eligibility_min_cgpa=None,
    eligibility_min_10=None,
    eligibility_min_12=None,
    eligibility_backlogs=None,
    package_lpa=None,
    deadline_date=None,
    location=None,
    position_type=None,
    has_ppo=False,
    tech_stack=None,
    tech_stack_inferred=False,
    prep_topics=None,
    application_link=None,
):
    eligibility_json = json.dumps(eligibility) if isinstance(eligibility, (list, dict)) else eligibility
    branches_json = json.dumps(eligibility_branches) if eligibility_branches else None

    with get_conn() as conn:
        try:
            conn.execute(
                """
                INSERT INTO placements (
                    message_id, date, company, roles, eligibility, ctc, deadline, mode,
                    summary, raw_message, eligibility_branches, eligibility_batch,
                    eligibility_min_cgpa, eligibility_min_10, eligibility_min_12,
                    eligibility_backlogs, package_lpa, deadline_date, location,
                    position_type, has_ppo, tech_stack, tech_stack_inferred, prep_topics,
                    application_link
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id, date, company, roles, eligibility_json, ctc, deadline, mode,
                    summary, raw_message, branches_json, eligibility_batch,
                    eligibility_min_cgpa, eligibility_min_10, eligibility_min_12,
                    eligibility_backlogs, package_lpa, deadline_date, location,
                    position_type, int(bool(has_ppo)), tech_stack, int(bool(tech_stack_inferred)),
                    prep_topics, application_link or "",
                ),
            )
        except sqlite3.IntegrityError:
            pass


def get_placement(placement_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM placements WHERE id = ?", (placement_id,)).fetchone()
        return dict(row) if row else None


def save_prep_plan(placement_id, plan):
    with get_conn() as conn:
        conn.execute(
            "UPDATE placements SET prep_plan = ? WHERE id = ?",
            (json.dumps(plan), placement_id),
        )


def purge_old_data(retention_days: int = 7):
    """Delete placements and processed_messages older than `retention_days` days.

    This keeps the DB to a rolling window of the last N days up to now.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat()

    with get_conn() as conn:
        result_p = conn.execute(
            """
            DELETE FROM placements
            WHERE date < ?
            """,
            (cutoff_str,),
        )
        deleted_placements = result_p.rowcount

        result_m = conn.execute(
            """
            DELETE FROM processed_messages
            WHERE processed_at < ?
            """,
            (cutoff_str,),
        )
        deleted_processed = result_m.rowcount

    print(
        f"[purge] cutoff={cutoff_str} | "
        f"deleted {deleted_placements} placements, "
        f"{deleted_processed} processed_message records"
    )
    return deleted_placements, deleted_processed


def get_all_placements():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM placements ORDER BY id DESC"
        ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            try:
                d["eligibility"] = json.loads(d["eligibility"]) if d.get("eligibility") else []
            except (json.JSONDecodeError, TypeError):
                d["eligibility"] = [d["eligibility"]] if d.get("eligibility") else []
            try:
                d["eligibility_branches"] = json.loads(d["eligibility_branches"]) if d.get("eligibility_branches") else None
            except (json.JSONDecodeError, TypeError):
                d["eligibility_branches"] = None
            try:
                d["prep_plan"] = json.loads(d["prep_plan"]) if d.get("prep_plan") else None
            except (json.JSONDecodeError, TypeError):
                d["prep_plan"] = None
            d["has_ppo"] = bool(d.get("has_ppo"))
            d["tech_stack_inferred"] = bool(d.get("tech_stack_inferred"))
            result.append(d)
        return result


def get_placements_count():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM placements"
        ).fetchone()
        return int(row["count"]) if row else 0


def get_backfill_state_summary():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT chat_id, last_message_id, last_message_date, updated_at FROM backfill_state ORDER BY chat_id"
        ).fetchall()
        return [dict(row) for row in rows]


def get_last_backfill_id(chat_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT last_message_id
            FROM backfill_state
            WHERE chat_id = ?
            LIMIT 1
            """,
            (str(chat_id),),
        ).fetchone()

        if row:
            return int(row["last_message_id"])

        legacy_row = conn.execute(
            """
            SELECT MAX(message_id) AS last_message_id
            FROM processed_messages
            """
        ).fetchone()

        return int(legacy_row["last_message_id"]) if legacy_row and legacy_row["last_message_id"] is not None else 0


def get_backfill_state(chat_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT chat_id, last_message_id, last_message_date, updated_at
            FROM backfill_state
            WHERE chat_id = ?
            LIMIT 1
            """,
            (str(chat_id),),
        ).fetchone()

        if row is None:
            return {"chat_id": str(chat_id), "last_message_id": 0, "last_message_date": None, "updated_at": None}

        return dict(row)


def set_last_backfill_id(chat_id, last_message_id, last_message_date=None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO backfill_state (chat_id, last_message_id, last_message_date, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id)
            DO UPDATE SET last_message_id = excluded.last_message_id,
                          last_message_date = COALESCE(excluded.last_message_date, backfill_state.last_message_date),
                          updated_at = CURRENT_TIMESTAMP
            """,
            (str(chat_id), int(last_message_id), last_message_date),
        )


def get_placements_missing_link():
    """Stored placements whose registration link has not been looked up yet."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT message_id, raw_message FROM placements WHERE application_link IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def set_application_link(message_id, link):
    with get_conn() as conn:
        conn.execute(
            "UPDATE placements SET application_link = ? WHERE message_id = ?",
            (link or "", message_id),
        )
