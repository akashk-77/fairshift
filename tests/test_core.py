import os
from datetime import datetime, timedelta

from app import timeutil as tu
from app.services import analytics, gemini, i18n, payroll

UTC = tu.UTC


def dt(d, h, m=0):
    return datetime(2026, 10, d, h, m, tzinfo=UTC)


# ---------- pure logic ----------
def test_overtime_is_daily_and_paid_at_multiplier():
    shifts = [(dt(5, 2), dt(5, 12)), (dt(6, 2), dt(6, 10))]  # 10h then 8h (local = UTC+5:30, same day)
    p = payroll.compute_payslip(shifts, rate=100, std_hours=8, ot_mult=2, tz_min=330)
    assert p["regular_hours"] == 16 and p["overtime_hours"] == 2
    assert p["basic_pay"] == 1600 and p["overtime_pay"] == 400 and p["gross"] == 2000
    assert p["pf"] == 192 and p["net"] == round(2000 - 192 - 15, 2)


def test_no_esi_above_limit():
    shifts = [(dt(d, 2), dt(d, 10)) for d in range(1, 27)]
    p = payroll.compute_payslip(shifts, rate=200, std_hours=8, ot_mult=2, tz_min=330)
    assert p["esi"] == 0


def test_fatigue_flags_back_to_back_and_weekly():
    now = dt(10, 12)
    shifts = [(dt(d, 7), dt(d, 20)) for d in range(4, 10)]  # 13h shifts, 11h rest? 20:00->07:00 = 11h
    shifts[2] = (dt(6, 6), dt(6, 20))  # shrinks gap after previous day to 10h
    f = analytics.fatigue(shifts, now, 0)
    assert "LONG_SHIFT" in f["flags"] and "BACK_TO_BACK" in f["flags"] and "WEEKLY_OVER_60" in f["flags"]
    assert f["level"] == "high"


def test_fatigue_low_for_normal_work():
    now = dt(10, 12)
    f = analytics.fatigue([(dt(8, 3), dt(8, 11)), (dt(9, 3), dt(9, 11))], now, 0)
    assert f["level"] == "low" and f["flags"] == []


def test_attrition_reasons_are_explained():
    a = analytics.attrition(70, 3, 10, 90, 1, 2.0)
    assert a["level"] == "high" and len(a["reasons"]) == 5


def test_payslip_labels_exist_for_all_languages():
    for lang in i18n.LANGS:
        assert set(i18n.labels(lang)) == set(i18n.KEYS)
    assert i18n.norm("xx") == "en"


def test_hazard_fallback_without_api_key():
    r = gemini.parse_hazard("Open wire sparking near the panel", "en")
    assert r["category"] == "electrical" and r["severity"] == "high" and r["ai"] is False


# ---------- API ----------
def test_auth_required(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/admin/overview").status_code == 401


def test_worker_token_cannot_reach_admin(client, worker):
    assert client.get("/api/admin/overview", headers=worker).status_code == 401


def test_bad_login(client):
    assert client.post("/api/auth/worker", json={"code": "FAC02", "pin": "9999"}).status_code == 401


def test_checkin_flow_with_qr(client, worker, admin):
    assert client.post("/api/shifts/check-in", json={"qr": "FS|2|wrong"}, headers=worker).status_code == 403
    svg = client.get("/api/admin/sites/2/qr.svg", headers=admin)
    assert svg.status_code == 200 and b"<svg" in svg.content
    from app.db import connect
    secret = connect().execute("SELECT qr_secret FROM sites WHERE id=2").fetchone()[0]
    r = client.post("/api/shifts/check-in", json={"qr": f"FS|2|{secret}"}, headers=worker)
    assert r.status_code == 200
    assert client.post("/api/shifts/check-in", json={"qr": f"FS|2|{secret}"}, headers=worker).status_code == 409
    assert client.get("/api/shifts/mine", headers=worker).json()["on_shift"] is True
    out = client.post("/api/shifts/check-out", headers=worker)
    assert out.status_code == 200 and "overtime_hours" in out.json()


def test_geofence_rejects_far_location(client, worker):
    r = client.post("/api/shifts/check-in", json={"lat": 28.6, "lng": 77.2}, headers=worker)
    assert r.status_code == 403


def test_payslip_in_tamil(client, worker):
    month = tu.now().strftime("%Y-%m")
    r = client.get(f"/api/payslip?month={month}&lang=ta", headers=worker).json()
    assert r["labels"]["net"] == "கையில் கிடைக்கும் சம்பளம்" and "net" in r["data"]
    assert client.get("/api/payslip?month=bad", headers=worker).status_code == 400


def test_safety_report_and_status_tracking(client, worker, admin):
    r = client.post("/api/safety", json={"description": "Fire smoke near the press machine", "lang": "en"},
                    headers=worker).json()
    assert r["category"] in ("fire", "machinery") and r["status"] == "open"
    assert client.patch(f"/api/admin/safety/{r['id']}", json={"status": "resolved", "admin_note": "Fixed"},
                        headers=admin).status_code == 200
    mine = client.get("/api/safety/mine", headers=worker).json()
    assert next(x for x in mine if x["id"] == r["id"])["status"] == "resolved"


def test_voice_report_needs_ai_when_no_key(client, worker):
    r = client.post("/api/safety/voice", json={"audio_b64": "A" * 200}, headers=worker)
    assert r.status_code == 503


def test_feedback_is_anonymous_and_rate_limited(client, worker):
    from app.db import connect
    cols = [c[1] for c in connect().execute("PRAGMA table_info(feedback)")]
    assert "worker_id" not in cols
    mid = client.get("/api/me", headers=worker).json()["managers"][0]["id"]
    assert client.post("/api/feedback", json={"manager_id": mid, "rating": 4}, headers=worker).status_code == 200
    assert client.post("/api/feedback", json={"manager_id": mid, "rating": 1}, headers=worker).status_code == 409
    assert client.post("/api/feedback", json={"manager_id": 1, "rating": 4}, headers=worker).status_code == 404


def test_admin_sector_toggle_isolated(client, admin):
    f = client.get("/api/admin/overview?sector=factory", headers=admin).json()
    h = client.get("/api/admin/overview?sector=hospital", headers=admin).json()
    a = client.get("/api/admin/overview?sector=all", headers=admin).json()
    assert f["workers"] == 8 and h["workers"] == 8 and a["workers"] == 32
    assert all(x["sector"] == "factory" for x in client.get("/api/admin/fatigue?sector=factory", headers=admin).json())
    assert client.get("/api/admin/overview?sector=bogus", headers=admin).status_code == 400


def test_seeded_overworked_worker_is_flagged(client, admin):
    rows = client.get("/api/admin/fatigue?sector=construction", headers=admin).json()
    assert rows[0]["level"] == "high" and rows[0]["flags"]


def test_attrition_and_feedback_endpoints(client, admin):
    assert client.get("/api/admin/attrition", headers=admin).json()[0]["score"] > 0
    fb = client.get("/api/admin/feedback", headers=admin).json()
    assert fb and all(x["reviews"] >= 3 for x in fb)
    assert len(client.get("/api/admin/attendance-trend?days=7", headers=admin).json()) == 7


def test_passport_and_skill_add(client, worker, admin):
    assert client.post("/api/admin/skills", headers=admin,
                       json={"worker_code": "FAC01", "name": "CNC level 2", "kind": "certification"}).status_code == 200
    p = client.get("/api/passport", headers=worker).json()
    assert any(s["name"] == "CNC level 2" for s in p["skills"])


def test_college_sector_and_conditions_feedback(client, admin, worker):
    c = client.get("/api/admin/overview?sector=education", headers=admin).json()
    assert c["workers"] == 8
    r = client.post("/api/feedback", json={"rating": 2, "comment": "No water"}, headers=worker)
    assert r.status_code == 200
    assert client.post("/api/feedback", json={"rating": 1}, headers=worker).status_code == 409
    fb = client.get("/api/admin/feedback?sector=factory", headers=admin).json()
    assert any(x["manager"].startswith("Working conditions") for x in fb)


def test_overdue_escalation_flag(client, admin):
    rows = client.get("/api/admin/safety?sector=construction", headers=admin).json()
    assert any(r["overdue"] for r in rows)
    assert client.get("/api/admin/overview?sector=construction", headers=admin).json()["overdue_safety"] >= 1


def test_both_interfaces_are_served(client):
    assert client.get("/").status_code == 200 and b"Worker app" in client.get("/").content
    assert client.get("/worker").status_code == 200
    assert client.get("/admin").status_code == 200


def test_meta_hides_admin_password_when_configured(client):
    m = client.get("/api/meta").json()
    assert m["demo"] is True and "admin_hint" not in m and "admin-pass" not in str(m)


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    from app import db as dbm
    from app.config import settings
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE feedback(id INTEGER PRIMARY KEY, site_id INT, manager_id INTEGER NOT NULL, rating INT, "
                    "comment TEXT, sentiment REAL, week TEXT, dedupe_hash TEXT UNIQUE);"
                    "INSERT INTO feedback VALUES(1,1,1,4,'ok',0.5,'2026-W40','h1');")
    c.close()
    object.__setattr__(settings, "db_path", str(p))
    try:
        dbm.init_db()
        cols = [r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(feedback)")]
        assert "topic" in cols and sqlite3.connect(p).execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1
    finally:
        object.__setattr__(settings, "db_path", os.environ["DB_PATH"])


def test_parallel_requests_like_a_real_browser(admin):
    """The dashboard fires many requests at once; each must get its own working DB connection."""
    import concurrent.futures as cf
    import httpx
    from app.main import app
    paths = ["overview", "attendance-trend", "fatigue", "attrition", "safety", "feedback"] * 4
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
        with cf.ThreadPoolExecutor(12) as ex:
            codes = list(ex.map(lambda p: c.get(f"/api/admin/{p}?sector=all", headers=admin).status_code, paths))
    assert set(codes) == {200}


def test_security_headers(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_overnight_shift_is_split_at_local_midnight():
    # UTC+05:30: 20:00 UTC is 01:30 local; this shift crosses local midnight.
    start = datetime(2026, 10, 5, 18, 30, tzinfo=UTC)  # local 00:00 next day
    end = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)    # local 10:00
    p = payroll.compute_payslip([(start, end)], rate=100, std_hours=8, ot_mult=2, tz_min=330)
    assert p["days_worked"] == 1
    assert p["regular_hours"] == 8 and p["overtime_hours"] == 2


def test_payslip_rejects_reversed_shift_interval():
    start, end = dt(6, 12), dt(6, 10)
    import pytest
    with pytest.raises(ValueError):
        payroll.compute_payslip([(start, end)], rate=100, std_hours=8, ot_mult=2, tz_min=330)


def test_meta_never_discloses_admin_password(client):
    body = client.get("/api/meta").json()
    assert "admin_hint" not in body
    assert "admin-pass" not in str(body)


def test_readiness_endpoint(client):
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["ready"] is True


# ---------- efficiency / robustness regressions ----------
def test_login_throttle_expires_resets_and_stays_bounded():
    import pytest
    from fastapi import HTTPException

    from app.security import LoginThrottle
    now = [0.0]
    th = LoginThrottle(limit=3, window_s=60, max_keys=5, clock=lambda: now[0])
    for _ in range(3):
        th.record_failure("a")
    with pytest.raises(HTTPException) as exc:
        th.check("a")
    assert exc.value.status_code == 429
    now[0] = 61  # window elapsed: allowed again
    th.check("a")
    for _ in range(3):
        th.record_failure("a")
    th.reset("a")  # a successful login clears the counter
    th.check("a")
    for i in range(5):
        th.record_failure(f"k{i}")
    now[0] = 500  # all earlier entries are stale; the next insert sweeps them so memory cannot grow unbounded
    th.record_failure("fresh")
    assert len(th) == 1


def test_month_bounds_respect_local_timezone():
    start, end = tu.month_bounds(2026, 12, 330)  # IST: local Dec 1 00:00 == Nov 30 18:30 UTC
    assert start == datetime(2026, 11, 30, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 12, 31, 18, 30, tzinfo=UTC)


def test_attendance_trend_counts_distinct_workers_per_local_day(tmp_path):
    import sqlite3

    from app.db import SCHEMA_SQL
    from app.services import workforce
    db = sqlite3.connect(tmp_path / "t.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    db.execute("INSERT INTO sites(id,name,sector,qr_secret) VALUES(1,'S','factory','x')")
    for i in (1, 2, 3):
        db.execute("INSERT INTO workers(id,code,name,pin_hash,site_id,hourly_rate,joined_on) "
                   "VALUES(?,?,?,'h',1,100,'2026-01-01')", (i, f"W{i}", f"W{i}"))
    # Local time is UTC+05:30. Worker 1 has two shifts that fall on local Oct 20 (one starts at 01:30 local,
    # i.e. 20:00 UTC the previous day); worker 3 starts at 23:30 local on Oct 19.
    for wid, start in [(1, dt(19, 20)), (1, dt(20, 2)), (2, dt(20, 3)), (3, dt(19, 18))]:
        db.execute("INSERT INTO shifts(worker_id,site_id,check_in,check_out) VALUES(?,1,?,?)",
                   (wid, tu.iso(start), tu.iso(start + timedelta(hours=8))))
    trend = workforce.attendance_trend(db, None, 3, now=dt(20, 12))
    assert [(d["date"], d["present"], d["pct"]) for d in trend] == [
        ("2026-10-18", 0, 0), ("2026-10-19", 1, 33), ("2026-10-20", 2, 67)]
    assert workforce.attendance_trend(db, "hospital", 3, now=dt(20, 12))[-1]["total"] == 0


def test_workforce_results_are_cached_briefly(client):
    from app.db import connect
    from app.services import workforce
    conn = connect()
    try:
        first = workforce.compute_workforce(conn, "factory")
        assert workforce.compute_workforce(conn, "factory") is first  # dashboard burst shares one computation
        assert workforce.compute_workforce(conn, "factory", now=tu.now()) is not first  # explicit clock bypasses
        workforce.clear_cache()
        assert workforce.compute_workforce(conn, "factory") is not first
    finally:
        conn.close()


def test_feedback_summary_attaches_comments_to_the_right_entry(client, admin):
    fb = client.get("/api/admin/feedback", headers=admin).json()
    assert fb
    seeded = {"Shouts and ignores breaks", "Listens and explains clearly"}
    conditions = {"No drinking water near the work area", "No water"}
    for entry in fb:
        assert len(entry["comments"]) <= 5
        allowed = conditions if entry["manager"].startswith("Working conditions") else seeded
        assert set(entry["comments"]) <= allowed


def test_insights_top_reasons_are_ordered_by_frequency(client, admin):
    from collections import Counter
    top = client.get("/api/admin/insights", headers=admin).json()["aggregate"]["top_reasons"]
    rows = client.get("/api/admin/attrition", headers=admin).json()
    counts = Counter(r for row in rows for r in row["reasons"])
    assert [counts[r] for r in top] == sorted(counts.values(), reverse=True)[:5]


def test_safety_status_filter_is_validated(client, admin):
    assert client.get("/api/admin/safety?status=bogus", headers=admin).status_code == 422
    assert client.get("/api/admin/safety?status=open", headers=admin).status_code == 200


def test_skill_dates_must_be_real_calendar_dates(client, admin):
    body = {"worker_code": "FAC01", "name": "CNC level 3", "kind": "training"}
    assert client.post("/api/admin/skills", headers=admin, json={**body, "issued_on": "2026-13-45"}).status_code == 422
    assert client.post("/api/admin/skills", headers=admin, json={**body, "issued_on": "2026-06-01"}).status_code == 200


def test_static_assets_are_gzip_compressed(client):
    r = client.get("/static/js/worker.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
