"""Joins DB rows with analytics: per-worker fatigue + attrition, attendance trend, manager ratings."""
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from .. import timeutil as tu
from ..config import settings
from . import analytics

# Matches every row when :sector is NULL, otherwise only that sector. Interpolated as a constant (never user input).
SECTOR_CLAUSE = "(:sector IS NULL OR s.sector=:sector)"
RECENT_DAYS = 14        # window used for fatigue and "recent" attendance
HISTORY_DAYS = 28       # how far back shifts are loaded (recent + prior fortnight)
RATING_WINDOW_DAYS = 90
MIN_REVIEWS = 3         # k-anonymity: hide aggregates built from fewer anonymous reviews
UNRESOLVED_AFTER_DAYS = 7
CACHE_TTL_S = 5.0

_cache: dict[tuple[str, str | None], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def manager_ratings(db, now: datetime) -> dict:
    """Average rating per manager over 90 days, only when >= 3 reviews (k-anonymity)."""
    since = tu.iso_week(now - timedelta(days=RATING_WINDOW_DAYS))
    rows = db.execute("SELECT manager_id, AVG(rating) a FROM feedback WHERE week>=? AND manager_id IS NOT NULL "
                      "GROUP BY manager_id HAVING COUNT(*)>=?", (since, MIN_REVIEWS)).fetchall()
    return {r["manager_id"]: r["a"] for r in rows}


def _active_days(shifts: list[analytics.Shift], tz_min: int) -> int:
    return len({tu.local_date(start, tz_min) for start, _ in shifts})


def compute_workforce(db, sector: str | None, now: datetime | None = None) -> list[dict]:
    """Per-worker fatigue/attrition. The result is shared and must be treated as read-only.

    The admin dashboard asks for this several times per page load (overview, fatigue, attrition,
    insights), so results are cached for a few seconds per (database, sector). Passing an explicit
    `now` bypasses the cache.
    """
    if now is not None:
        return _compute(db, sector, now)
    key = (settings.db_path, sector)
    with _cache_lock:  # held while computing so concurrent dashboard requests share one computation
        hit = _cache.get(key)
        if hit and time.monotonic() < hit[0]:
            return hit[1]
        result = _compute(db, sector, tu.now())
        _cache[key] = (time.monotonic() + CACHE_TTL_S, result)
        return result


def _compute(db, sector: str | None, now: datetime) -> list[dict]:
    tz = settings.tz_offset_min
    params = {"sector": sector}
    workers = db.execute(
        "SELECT w.id,w.code,w.name,w.job_title,w.joined_on,w.manager_id,s.name site_name,s.sector,m.name manager_name "
        f"FROM workers w JOIN sites s ON s.id=w.site_id LEFT JOIN managers m ON m.id=w.manager_id WHERE {SECTOR_CLAUSE}",
        params).fetchall()
    if not workers:
        return []

    by_worker = defaultdict(list)
    for r in db.execute("SELECT sh.worker_id,sh.check_in,sh.check_out FROM shifts sh JOIN workers w ON w.id=sh.worker_id "
                        f"JOIN sites s ON s.id=w.site_id WHERE sh.check_in>=:since AND {SECTOR_CLAUSE}",
                        {**params, "since": tu.iso(now - timedelta(days=HISTORY_DAYS))}):
        by_worker[r["worker_id"]].append((tu.parse(r["check_in"]), tu.parse(r["check_out"]) if r["check_out"] else now))

    unresolved = {r["worker_id"]: r["c"] for r in db.execute(
        "SELECT r.worker_id,COUNT(*) c FROM safety_reports r JOIN workers w ON w.id=r.worker_id "
        f"JOIN sites s ON s.id=w.site_id WHERE r.status!='resolved' AND r.created_at<:before AND {SECTOR_CLAUSE} "
        "GROUP BY r.worker_id", {**params, "before": tu.iso(now - timedelta(days=UNRESOLVED_AFTER_DAYS))})}
    ratings = manager_ratings(db, now)

    recent_from = now - timedelta(days=RECENT_DAYS)
    out = []
    for w in workers:
        shifts = by_worker.get(w["id"], [])
        recent = [x for x in shifts if x[0] >= recent_from]
        prior = [x for x in shifts if x[0] < recent_from]
        fat = analytics.fatigue(recent, now, tz)
        recent_days = _active_days(recent, tz)
        tenure = (now.date() - date.fromisoformat(w["joined_on"])).days
        attr = analytics.attrition(fat["score"], recent_days, _active_days(prior, tz), tenure,
                                   unresolved.get(w["id"], 0), ratings.get(w["manager_id"]))
        out.append({"worker_id": w["id"], "code": w["code"], "name": w["name"], "job_title": w["job_title"],
                    "site": w["site_name"], "sector": w["sector"], "manager": w["manager_name"],
                    "fatigue": fat, "attrition": attr, "days_last_14": recent_days})
    return out


def attendance_trend(db, sector: str | None, days: int, now: datetime | None = None) -> list[dict]:
    """Distinct workers with a check-in per local day, for the last `days` days (oldest first).

    Aggregation happens in SQLite (grouped by local date) instead of parsing every shift in Python.
    """
    now = now or tu.now()
    tz = settings.tz_offset_min
    params = {"sector": sector}
    total = db.execute("SELECT COUNT(*) FROM workers w JOIN sites s ON s.id=w.site_id "
                       f"WHERE {SECTOR_CLAUSE}", params).fetchone()[0]
    present = {r["day"]: r["n"] for r in db.execute(
        "SELECT date(sh.check_in, :shift) day, COUNT(DISTINCT sh.worker_id) n FROM shifts sh "
        "JOIN workers w ON w.id=sh.worker_id JOIN sites s ON s.id=w.site_id "
        f"WHERE sh.check_in>=:since AND {SECTOR_CLAUSE} GROUP BY day",
        {**params, "shift": f"{tz:+d} minutes", "since": tu.iso(now - timedelta(days=days + 1))})}
    today = tu.local_date(now, tz)
    trend = []
    for offset in range(days - 1, -1, -1):
        day = str(today - timedelta(days=offset))
        n = present.get(day, 0)
        trend.append({"date": day, "present": n, "total": total, "pct": round(100 * n / total) if total else 0})
    return trend
