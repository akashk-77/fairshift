import hashlib
import hmac
import io
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import timeutil as tu
from .config import settings
from .db import get_db
from .security import admin_claims, login_throttle, make_token, verify_pin, worker_claims
from .services import analytics, gemini, i18n, payroll, workforce
from .services.workforce import SECTOR_CLAUSE

router = APIRouter(prefix="/api")

SECTORS = frozenset({"construction", "factory", "hospital", "education"})
Status = Literal["open", "acknowledged", "in_progress", "resolved"]
STALE_SHIFT_HOURS = 20          # an open shift older than this is auto-closed on check-in / needs review on check-out
URGENT_SEVERITIES = frozenset({"high", "critical"})
URGENT_OVERDUE = timedelta(days=2)
NORMAL_OVERDUE = timedelta(days=7)
SEVERITY_ORDER = "CASE r.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
COMMENTS_PER_ENTRY = 5


# ---------- helpers ----------
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _sector(sector: str | None) -> str | None:
    if sector in (None, "", "all"):
        return None
    if sector not in SECTORS:
        raise HTTPException(400, "Unknown sector")
    return sector


def _me(db, claims) -> dict:
    w = db.execute("SELECT w.*, s.name site_name, s.sector, s.lat, s.lng, s.radius_m, s.qr_secret, "
                   "s.std_daily_hours, s.ot_multiplier FROM workers w JOIN sites s ON s.id=w.site_id WHERE w.id=?",
                   (claims["sub"],)).fetchone()
    if not w:
        raise HTTPException(401, "Unknown worker")
    return dict(w)


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def _overdue(severity: str, status: str, created: str, now) -> bool:
    """Escalation rule: high/critical hazards unresolved > 2 days, others > 7 days."""
    if status == "resolved":
        return False
    return now - tu.parse(created) > (URGENT_OVERDUE if severity in URGENT_SEVERITIES else NORMAL_OVERDUE)


def _hours(row, now) -> float:
    return payroll.shift_hours(tu.parse(row["check_in"]), tu.parse(row["check_out"]) if row["check_out"] else now)


def _count_high(wf: list[dict], kind: str) -> int:
    return sum(x[kind]["level"] == "high" for x in wf)


@router.get("/meta")
def meta():
    return {"demo": settings.seed_demo}


# ---------- auth ----------
class WorkerLogin(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    pin: str = Field(min_length=4, max_length=12)


class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/worker")
def login_worker(body: WorkerLogin, request: Request, db=Depends(get_db)):
    code = body.code.strip().upper()
    key = f"w:{_client_ip(request)}:{code}"
    login_throttle.check(key)
    w = db.execute("SELECT id, pin_hash, language FROM workers WHERE code=?", (code,)).fetchone()
    if not verify_pin(body.pin, w["pin_hash"] if w else None):
        login_throttle.record_failure(key)
        raise HTTPException(401, "Wrong code or PIN")
    login_throttle.reset(key)
    return {"token": make_token(w["id"], "worker"), "language": w["language"]}


@router.post("/auth/admin")
def login_admin(body: AdminLogin, request: Request):
    key = f"a:{_client_ip(request)}"
    login_throttle.check(key)
    if not hmac.compare_digest(body.password.encode(), settings.admin_password.encode()):
        login_throttle.record_failure(key)
        raise HTTPException(401, "Wrong password")
    login_throttle.reset(key)
    return {"token": make_token(0, "admin")}


# ---------- worker: profile & shifts ----------
@router.get("/me")
def me(claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    managers = [dict(r) for r in db.execute("SELECT id,name FROM managers WHERE site_id=?", (w["site_id"],))]
    return {"name": w["name"], "code": w["code"], "job_title": w["job_title"], "site": w["site_name"],
            "sector": w["sector"], "language": w["language"], "managers": managers}


class CheckIn(BaseModel):
    qr: str | None = Field(None, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


def _open_shift(db, worker_id: int):
    # The partial unique index guarantees at most one open shift per worker.
    return db.execute("SELECT * FROM shifts WHERE worker_id=? AND check_out IS NULL", (worker_id,)).fetchone()


def _verify_presence(body: CheckIn, w: dict) -> str:
    """Return the check-in method ('qr' or 'location') or raise if the worker cannot prove presence."""
    if body.qr:
        parts = body.qr.split("|")
        ok = (len(parts) == 3 and parts[0] == "FS" and parts[1] == str(w["site_id"])
              and hmac.compare_digest(parts[2], w["qr_secret"]))
        if not ok:
            raise HTTPException(403, "This QR is not for your site")
        return "qr"
    if body.lat is not None and body.lng is not None and w["lat"] is not None:
        if _haversine_m(body.lat, body.lng, w["lat"], w["lng"]) > w["radius_m"]:
            raise HTTPException(403, "You are too far from the site")
        return "location"
    raise HTTPException(400, "Scan the site QR or share your location")


@router.post("/shifts/check-in")
def check_in(body: CheckIn, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    method = _verify_presence(body, w)
    now = tu.now()
    open_ = _open_shift(db, w["id"])
    if open_:
        started = tu.parse(open_["check_in"])
        if now - started < timedelta(hours=STALE_SHIFT_HOURS):
            raise HTTPException(409, "Already checked in")
        db.execute("UPDATE shifts SET check_out=?, auto_closed=1 WHERE id=?",
                   (tu.iso(started + timedelta(hours=w["std_daily_hours"])), open_["id"]))
    try:
        db.execute("INSERT INTO shifts(worker_id,site_id,check_in,method) VALUES(?,?,?,?)",
                   (w["id"], w["site_id"], tu.iso(now), method))
    except sqlite3.IntegrityError as exc:
        # The partial unique index is the final guard against simultaneous check-ins.
        if "idx_one_open_shift_per_worker" in str(exc) or "UNIQUE constraint failed: shifts.worker_id" in str(exc):
            raise HTTPException(409, "Already checked in") from exc
        raise
    return {"status": "checked_in", "at": tu.iso(now), "method": method}


@router.post("/shifts/check-out")
def check_out(claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    open_ = _open_shift(db, w["id"])
    if not open_:
        raise HTTPException(409, "You are not checked in")
    now = tu.now()
    hrs = payroll.shift_hours(tu.parse(open_["check_in"]), now)
    if hrs > STALE_SHIFT_HOURS:
        raise HTTPException(409, "This shift is over 20 hours old and needs supervisor review before checkout")
    db.execute("UPDATE shifts SET check_out=? WHERE id=?", (tu.iso(now), open_["id"]))
    return {"status": "checked_out", "hours": round(hrs, 2),
            "overtime_hours": round(max(0, hrs - w["std_daily_hours"]), 2)}


@router.get("/shifts/mine")
def my_shifts(days: int = Query(14, ge=1, le=60), claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    now = tu.now()
    rows = db.execute("SELECT check_in,check_out FROM shifts WHERE worker_id=? AND check_in>=? ORDER BY check_in DESC",
                      (w["id"], tu.iso(now - timedelta(days=days)))).fetchall()
    shifts = []
    for r in rows:
        hrs = _hours(r, now)
        shifts.append({"check_in": r["check_in"], "check_out": r["check_out"], "hours": round(hrs, 2),
                       "overtime_hours": round(max(0, hrs - w["std_daily_hours"]), 2)})
    open_ = next((r for r in rows if not r["check_out"]), None)
    return {"on_shift": open_ is not None, "since": open_["check_in"] if open_ else None,
            "std_hours": w["std_daily_hours"], "shifts": shifts}


# ---------- worker: payslip ----------
def _payslip(db, w: dict, month: str) -> dict:
    if not MONTH_RE.fullmatch(month):
        raise HTTPException(400, "month must be YYYY-MM")
    start, end = tu.month_bounds(int(month[:4]), int(month[5:]), settings.tz_offset_min)
    rows = db.execute("SELECT check_in,check_out FROM shifts WHERE worker_id=? AND check_in>=? AND check_in<? "
                      "AND check_out IS NOT NULL", (w["id"], tu.iso(start), tu.iso(end))).fetchall()
    shifts = [(tu.parse(r["check_in"]), tu.parse(r["check_out"])) for r in rows]
    try:
        return payroll.compute_payslip(shifts, w["hourly_rate"], w["std_daily_hours"], w["ot_multiplier"],
                                       settings.tz_offset_min)
    except ValueError as exc:  # corrupt interval or invalid pay configuration: needs a human, not a 500
        raise HTTPException(422, "Payslip cannot be calculated until attendance or pay settings are reviewed") from exc


@router.get("/payslip")
def payslip(month: str, lang: str | None = None, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    lang = i18n.norm(lang or w["language"])
    p = _payslip(db, w, month)
    return {"month": month, "lang": lang, "labels": i18n.labels(lang), "data": p,
            "summary": i18n.summary(lang, p), "ot_multiplier": w["ot_multiplier"]}


@router.get("/payslip/explain")
def payslip_explain(month: str, lang: str | None = None, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    lang = i18n.norm(lang or w["language"])
    return {"lang": lang, "text": gemini.explain_payslip(lang, _payslip(db, w, month))}


# ---------- worker: safety ----------
class SafetyIn(BaseModel):
    description: str = Field(min_length=3, max_length=1500)
    lang: str = "en"
    location: str | None = Field(None, max_length=120)


class VoiceIn(BaseModel):
    audio_b64: str = Field(min_length=100, max_length=2_000_000)
    mime: Literal["audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"] = "audio/webm"
    lang: str = "en"


def _store_report(db, w, text, parsed, lang, location):
    now = tu.iso(tu.now())
    rid = db.execute(
        "INSERT INTO safety_reports(worker_id,site_id,category,severity,location,description,summary,lang,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (w["id"], w["site_id"], parsed["category"], parsed["severity"], location or parsed["location"],
         text, parsed["summary"], i18n.norm(lang), now, now)).lastrowid
    return {"id": rid, "category": parsed["category"], "severity": parsed["severity"],
            "summary": parsed["summary"], "status": "open", "ai": parsed["ai"], "transcript": text}


@router.post("/safety")
def report_safety(body: SafetyIn, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    return _store_report(db, w, body.description.strip(), gemini.parse_hazard(body.description, body.lang),
                         body.lang, body.location)


@router.post("/safety/voice")
def report_safety_voice(body: VoiceIn, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    parsed = gemini.transcribe_hazard(body.audio_b64, body.mime, body.lang)
    if not parsed:
        raise HTTPException(503, "Voice reports need the AI service. Please type your report.")
    return _store_report(db, w, parsed["transcript"], parsed, body.lang, None)


@router.get("/safety/mine")
def my_reports(claims=Depends(worker_claims), db=Depends(get_db)):
    rows = db.execute("SELECT id,category,severity,summary,status,admin_note,created_at FROM safety_reports "
                      "WHERE worker_id=? ORDER BY id DESC LIMIT 30", (claims["sub"],)).fetchall()
    return [dict(r) for r in rows]


# ---------- worker: anonymous feedback ----------
class FeedbackIn(BaseModel):
    manager_id: int | None = None  # None = review of working conditions at the site
    rating: int = Field(ge=1, le=5)
    comment: str = Field("", max_length=600)


@router.post("/feedback")
def feedback(body: FeedbackIn, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    mid = None
    if body.manager_id is not None:
        m = db.execute("SELECT id FROM managers WHERE id=? AND site_id=?", (body.manager_id, w["site_id"])).fetchone()
        if not m:
            raise HTTPException(404, "Manager not found at your site")
        mid = m["id"]
    week = tu.iso_week(tu.now())
    # One-way token limits spam to 1 review / manager / week. The worker id itself is NEVER stored.
    dedupe = hmac.new(settings.secret_key.encode(), f"{w['id']}|{mid or 'site'}|{week}".encode(),
                      hashlib.sha256).hexdigest()
    if db.execute("SELECT 1 FROM feedback WHERE dedupe_hash=?", (dedupe,)).fetchone():
        raise HTTPException(409, "You already sent this review this week")
    comment = body.comment.strip()
    db.execute("INSERT INTO feedback(site_id,manager_id,topic,rating,comment,sentiment,week,dedupe_hash) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (w["site_id"], mid, "manager" if mid else "conditions", body.rating, comment,
                gemini.sentiment(comment, body.rating), week, dedupe))
    return {"status": "received"}


# ---------- worker: skill passport ----------
@router.get("/passport")
def passport(claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    skills = [dict(r) for r in db.execute(
        "SELECT name,kind,issuer,issued_on,expires_on FROM skills WHERE worker_id=? ORDER BY issued_on DESC", (w["id"],))]
    tenure = db.execute("SELECT COUNT(*) FROM shifts WHERE worker_id=? AND check_out IS NOT NULL", (w["id"],)).fetchone()[0]
    return {"name": w["name"], "code": w["code"], "job_title": w["job_title"], "sector": w["sector"],
            "employer_site": w["site_name"], "joined_on": w["joined_on"], "verified_shifts": tenure, "skills": skills}


# ---------- admin ----------
@router.get("/admin/sites")
def admin_sites(_=Depends(admin_claims), db=Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT id,name,sector FROM sites ORDER BY sector,name")]


@lru_cache(maxsize=64)
def _qr_svg(payload: str) -> bytes:
    buf = io.BytesIO()
    segno.make(payload, error="m").save(buf, kind="svg", scale=8, border=2)
    return buf.getvalue()


@router.get("/admin/sites/{site_id}/qr.svg")
def site_qr(site_id: int, _=Depends(admin_claims), db=Depends(get_db)):
    s = db.execute("SELECT id,qr_secret FROM sites WHERE id=?", (site_id,)).fetchone()
    if not s:
        raise HTTPException(404, "No such site")
    return Response(_qr_svg(f"FS|{s['id']}|{s['qr_secret']}"), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.get("/admin/overview")
def overview(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    sec = _sector(sector)
    params = {"sector": sec}
    now = tu.now()
    wf = workforce.compute_workforce(db, sec)
    on_shift = db.execute("SELECT COUNT(*) FROM shifts sh JOIN sites s ON s.id=sh.site_id "
                          f"WHERE sh.check_out IS NULL AND {SECTOR_CLAUSE}", params).fetchone()[0]
    avg = db.execute("SELECT AVG(rating) FROM feedback fb JOIN sites s ON s.id=fb.site_id "
                     f"WHERE fb.manager_id IS NOT NULL AND {SECTOR_CLAUSE}", params).fetchone()[0]
    open_reports = db.execute("SELECT r.severity,r.status,r.created_at FROM safety_reports r "
                              f"JOIN sites s ON s.id=r.site_id WHERE r.status!='resolved' AND {SECTOR_CLAUSE}",
                              params).fetchall()
    overdue = sum(_overdue(r["severity"], r["status"], r["created_at"], now) for r in open_reports)
    today = workforce.attendance_trend(db, sec, 1, now)[-1]
    return {"sector": sec or "all", "workers": len(wf), "on_shift_now": on_shift,
            "attendance_today_pct": today["pct"], "high_fatigue": _count_high(wf, "fatigue"),
            "high_attrition": _count_high(wf, "attrition"), "open_safety": len(open_reports),
            "overdue_safety": overdue, "avg_rating": round(avg, 2) if avg else None}


@router.get("/admin/attendance-trend")
def trend(sector: str | None = None, days: int = Query(14, ge=3, le=30), _=Depends(admin_claims), db=Depends(get_db)):
    return workforce.attendance_trend(db, _sector(sector), days)


@router.get("/admin/fatigue")
def fatigue_list(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    wf = workforce.compute_workforce(db, _sector(sector))
    rows = [{"code": x["code"], "name": x["name"], "site": x["site"], "sector": x["sector"], **x["fatigue"]} for x in wf]
    return sorted(rows, key=lambda r: -r["score"])


@router.get("/admin/attrition")
def attrition_list(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    wf = workforce.compute_workforce(db, _sector(sector))
    rows = [{"code": x["code"], "name": x["name"], "site": x["site"], "sector": x["sector"],
             "manager": x["manager"], **x["attrition"]} for x in wf]
    return sorted(rows, key=lambda r: -r["score"])


@router.get("/admin/safety")
def admin_safety(sector: str | None = None, status: Status | None = None, _=Depends(admin_claims),
                 db=Depends(get_db)):
    now = tu.now()
    rows = [dict(r) for r in db.execute(
        "SELECT r.id,r.category,r.severity,r.location,r.summary,r.description,r.status,r.admin_note,r.created_at,"
        "s.name site,s.sector,w.code worker FROM safety_reports r JOIN sites s ON s.id=r.site_id "
        f"JOIN workers w ON w.id=r.worker_id WHERE {SECTOR_CLAUSE} AND (:status IS NULL OR r.status=:status) "
        f"ORDER BY {SEVERITY_ORDER}, r.id DESC LIMIT 100", {"sector": _sector(sector), "status": status})]
    for r in rows:
        r["overdue"] = _overdue(r["severity"], r["status"], r["created_at"], now)
    return rows


class StatusIn(BaseModel):
    status: Status
    admin_note: str | None = Field(None, max_length=300)


@router.patch("/admin/safety/{rid}")
def update_safety(rid: int, body: StatusIn, _=Depends(admin_claims), db=Depends(get_db)):
    cur = db.execute("UPDATE safety_reports SET status=?, admin_note=COALESCE(?,admin_note), updated_at=? WHERE id=?",
                     (body.status, body.admin_note, tu.iso(tu.now()), rid))
    if not cur.rowcount:
        raise HTTPException(404, "No such report")
    return {"id": rid, "status": body.status}


def _recent_comments(db, key: str, ids: list[int], where: str = "1=1") -> dict[int, list[str]]:
    """Latest non-empty comments for many managers/sites in ONE query (window function, no N+1).

    `key` and `where` are internal constants, never user input.
    """
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT k, comment FROM (SELECT {key} k, comment, ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY id DESC) rn "
        f"FROM feedback WHERE comment!='' AND {where} AND {key} IN ({marks})) WHERE rn<=? ORDER BY k, rn",
        [*ids, COMMENTS_PER_ENTRY])
    out: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        out[r["k"]].append(r["comment"])
    return out


@router.get("/admin/feedback")
def feedback_summary(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    """Managers/sites with fewer than 3 reviews are hidden so a single worker can't be identified."""
    params = {"sector": _sector(sector), "min_reviews": workforce.MIN_REVIEWS}
    managers = db.execute(
        "SELECT m.id,m.name,s.name site,s.sector,COUNT(*) n,AVG(fb.rating) avg_rating,AVG(fb.sentiment) sentiment "
        "FROM feedback fb JOIN managers m ON m.id=fb.manager_id JOIN sites s ON s.id=fb.site_id "
        f"WHERE {SECTOR_CLAUSE} GROUP BY m.id HAVING COUNT(*)>=:min_reviews ORDER BY avg_rating", params).fetchall()
    sites = db.execute(
        "SELECT s.id,s.name site,s.sector,COUNT(*) n,AVG(fb.rating) avg_rating,AVG(fb.sentiment) sentiment "
        "FROM feedback fb JOIN sites s ON s.id=fb.site_id "
        f"WHERE fb.topic='conditions' AND {SECTOR_CLAUSE} GROUP BY s.id HAVING COUNT(*)>=:min_reviews",
        params).fetchall()
    manager_comments = _recent_comments(db, "manager_id", [m["id"] for m in managers])
    site_comments = _recent_comments(db, "site_id", [s["id"] for s in sites], "topic='conditions'")

    def entry(label, r, comments):
        return {"manager": label, "site": r["site"], "sector": r["sector"], "reviews": r["n"],
                "avg_rating": round(r["avg_rating"], 2), "sentiment": round(r["sentiment"] or 0, 2),
                "comments": comments}
    return ([entry(m["name"], m, manager_comments.get(m["id"], [])) for m in managers]
            + [entry("Working conditions (whole site)", s, site_comments.get(s["id"], [])) for s in sites])


class SkillIn(BaseModel):
    worker_code: str = Field(max_length=20)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["training", "certification", "experience"]
    issuer: str | None = Field(None, max_length=80)
    issued_on: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_on: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("issued_on", "expires_on")
    @classmethod
    def check_real_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)  # ValueError -> HTTP 422 for impossible dates such as 2026-13-45
        return value


@router.post("/admin/skills")
def add_skill(body: SkillIn, _=Depends(admin_claims), db=Depends(get_db)):
    w = db.execute("SELECT id FROM workers WHERE code=?", (body.worker_code.strip().upper(),)).fetchone()
    if not w:
        raise HTTPException(404, "No worker with that code")
    db.execute("INSERT INTO skills(worker_id,name,kind,issuer,issued_on,expires_on) VALUES(?,?,?,?,?,?)",
               (w["id"], body.name, body.kind, body.issuer, body.issued_on, body.expires_on))
    return {"status": "added"}


@router.get("/admin/insights")
def insights(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    sec = _sector(sector)
    wf = workforce.compute_workforce(db, sec)
    reasons = Counter(r for x in wf for r in x["attrition"]["reasons"])
    agg = {"sector": sec or "all", "workers": len(wf), "high_fatigue": _count_high(wf, "fatigue"),
           "high_quit_risk": _count_high(wf, "attrition"),
           "top_reasons": [reason for reason, _ in reasons.most_common(5)]}  # most frequent first
    text = gemini.insights(agg)
    if not text:
        text = (f"{agg['high_fatigue']} of {agg['workers']} workers show high fatigue: cap overtime and enforce "
                f"{analytics.MIN_REST_HOURS}-hour rest gaps. {agg['high_quit_risk']} are at high quit risk: hold "
                "stay-conversations, resolve open safety reports and review low-rated managers.")
    return {"ai": gemini.available(), "text": text, "aggregate": agg}
