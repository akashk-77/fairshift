import sqlite3
from collections.abc import Iterator
from pathlib import Path

from .config import settings

SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text()


def connect() -> sqlite3.Connection:
    # One connection per request, used sequentially; FastAPI may open/close it on different pool threads.
    conn = sqlite3.connect(settings.db_path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _assert_no_duplicate_open_shifts(conn: sqlite3.Connection) -> None:
    """Do not silently discard or rewrite legacy attendance records; explain how to resolve them."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shifts'").fetchone():
        return
    if conn.execute("SELECT 1 FROM shifts WHERE check_out IS NULL "
                    "GROUP BY worker_id HAVING COUNT(*) > 1 LIMIT 1").fetchone():
        raise RuntimeError("Database contains multiple open shifts for one worker. Review and close "
                           "duplicate records before starting FairShift; no records were changed.")


def _feedback_table_is_legacy(conn: sqlite3.Connection) -> bool:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(feedback)")]
    return bool(cols) and "topic" not in cols


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # persistent in the DB file, so set once here, not per request
        _assert_no_duplicate_open_shifts(conn)
        legacy_feedback = _feedback_table_is_legacy(conn)  # older DB: rebuild so manager_id is nullable + topic exists
        if legacy_feedback:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("ALTER TABLE feedback RENAME TO feedback_old")
        conn.executescript(SCHEMA_SQL)  # idempotent (IF NOT EXISTS): creates tables and indexes
        if legacy_feedback:
            conn.execute("INSERT INTO feedback(id,site_id,manager_id,rating,comment,sentiment,week,dedupe_hash) "
                         "SELECT id,site_id,manager_id,rating,comment,sentiment,week,dedupe_hash FROM feedback_old")
            conn.execute("DROP TABLE feedback_old")
            conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
