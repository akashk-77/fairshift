"""Joins DB rows with analytics: per-worker fatigue + attrition, attendance trend, manager ratings."""
from collections import defaultdict
from datetime import datetime, timedelta

from .. import timeutil as tu
from ..config import settings
from . import analytics


def manager_ratings(db, now: datetime) -> dict:
    """Average rating per manager over 90 days, only when >= 3 reviews (k-anonymity)."""
    since = tu.iso_week(now - timedelta(days=90))
    rows = db.execute("SELECT manager_id, AVG(rating) a FROM feedback WHERE week>=? AND manager_id IS NOT NULL "
                      "GROUP BY manager_id HAVING COUNT(*)>=3", (since,)).fetchall()
    return {r["manager_id"]: r["a"] for r in rows}


def compute_workforce(db, sector: str | None, now: datetime | None = None) -> list[dict]:
    now = now or tu.now()
    tz = settings.tz_offset_min
    q = ("SELECT w.id,w.code,w.name,w.job_title,w.joined_on,w.manager_id,s.id site_id,s.name site_name,"
         "s.sector,m.name manager_name FROM workers w JOIN sites s ON s.id=w.site_id "
         "LEFT JOIN managers m ON m.id=w.manager_id")
    workers = db.execute(q + (" WHERE s.sector=?" if sector else ""), (sector,) if sector else ()).fetchall()
    if not workers:
        return []
    ids = [w["id"] for w in workers]
    ph = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT worker_id,check_in,check_out FROM shifts WHERE worker_id IN ({ph}) AND check_in>=?",
                      [*ids, tu.iso(now - timedelta(days=28))]).fetchall()
    by = defaultdict(list)
    for r in rows:
        by[r["worker_id"]].append((tu.parse(r["check_in"]), tu.parse(r["check_out"]) if r["check_out"] else now))
    unresolved = {r["worker_id"]: r["c"] for r in db.execute(
        f"SELECT worker_id,COUNT(*) c FROM safety_reports WHERE status!='resolved' AND created_at<? "
        f"AND worker_id IN ({ph}) GROUP BY worker_id", [tu.iso(now - timedelta(days=7)), *ids])}
    ratings = manager_ratings(db, now)
    out = []
    for w in workers:
        sh = by.get(w["id"], [])
        recent = [x for x in sh if x[0] >= now - timedelta(days=14)]
        prior = [x for x in sh if x[0] < now - timedelta(days=14)]
        f = analytics.fatigue(recent, now, tz)
        days = lambda lst: len({tu.local_date(s, tz) for s, _ in lst})  # noqa: E731
        tenure = (now.date() - datetime.strptime(w["joined_on"], "%Y-%m-%d").date()).days
        a = analytics.attrition(f["score"], days(recent), days(prior), tenure,
                                unresolved.get(w["id"], 0), ratings.get(w["manager_id"]))
        out.append({"worker_id": w["id"], "code": w["code"], "name": w["name"], "job_title": w["job_title"],
                    "site": w["site_name"], "sector": w["sector"], "manager": w["manager_name"],
                    "fatigue": f, "attrition": a, "days_last_14": days(recent)})
    return out


def attendance_trend(db, sector: str | None, days: int, now: datetime | None = None) -> list[dict]:
    now = now or tu.now()
    tz = settings.tz_offset_min
    sql = ("FROM shifts sh JOIN workers w ON w.id=sh.worker_id JOIN sites s ON s.id=w.site_id WHERE sh.check_in>=?")
    args = [tu.iso(now - timedelta(days=days + 1))]
    if sector:
        sql += " AND s.sector=?"; args.append(sector)
    total = db.execute("SELECT COUNT(*) c FROM workers w JOIN sites s ON s.id=w.site_id" +
                       (" WHERE s.sector=?" if sector else ""), (sector,) if sector else ()).fetchone()["c"]
    per = defaultdict(set)
    for r in db.execute("SELECT sh.worker_id, sh.check_in " + sql, args):
        per[tu.local_date(tu.parse(r["check_in"]), tz)].add(r["worker_id"])
    today = tu.local_date(now, tz)
    return [{"date": str(d), "present": len(per.get(d, ())), "total": total,
             "pct": round(100 * len(per.get(d, ())) / total) if total else 0}
            for d in (today - timedelta(days=i) for i in range(days - 1, -1, -1))]
