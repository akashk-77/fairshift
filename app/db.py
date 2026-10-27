import sqlite3
from pathlib import Path

from .config import settings

SCHEMA = Path(__file__).with_name("schema.sql")


def connect() -> sqlite3.Connection:
    # One connection per request, used sequentially; FastAPI may open/close it on different pool threads.
    conn = sqlite3.connect(settings.db_path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        # Do not silently discard or rewrite legacy attendance records. Explain how to
        # resolve duplicates before installing the new uniqueness invariant.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shifts'").fetchone():
            duplicates = conn.execute(
                "SELECT worker_id, COUNT(*) n FROM shifts WHERE check_out IS NULL "
                "GROUP BY worker_id HAVING COUNT(*) > 1 LIMIT 1"
            ).fetchone()
            if duplicates:
                raise RuntimeError(
                    "Database contains multiple open shifts for one worker. Review and close "
                    "duplicate records before starting FairShift; no records were changed."
                )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(feedback)")]
        if cols and "topic" not in cols:  # older DB: rebuild feedback so manager_id is nullable + topic exists
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("ALTER TABLE feedback RENAME TO feedback_old")
            conn.executescript(SCHEMA.read_text())
            conn.execute("INSERT INTO feedback(id,site_id,manager_id,rating,comment,sentiment,week,dedupe_hash) "
                         "SELECT id,site_id,manager_id,rating,comment,sentiment,week,dedupe_hash FROM feedback_old")
            conn.execute("DROP TABLE feedback_old")
            conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA.read_text())
        conn.commit()
    finally:
        conn.close()


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
