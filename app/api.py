import hashlib
import hmac
import io
import math
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Literal

import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import timeutil as tu
from .config import settings
from .db import get_db
from .security import admin_claims, make_token, verify_pin, worker_claims
from .services import analytics, gemini, i18n, payroll, workforce

router = APIRouter(prefix="/api")
SECTORS = {"construction", "factory", "hospital", "education"}
_fails: dict[str, list[float]] = {}


# ---------- helpers ----------
def _throttle(key: str) -> None:
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < 60]
    if len(_fails[key]) >= 5:
        raise HTTPException(429, "Too many attempts. Wait a minute.")


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


def _overdue(severity: str, status: str, created: str) -> bool:
    """Escalation rule: high/critical hazards unresolved > 2 days, others > 7 days."""
    if status == "resolved":
        return False
    limit = timedelta(days=2) if severity in ("high", "critical") else timedelta(days=7)
    return tu.now() - tu.parse(created) > limit


def _hours(row) -> float:
    return payroll.shift_hours(tu.parse(row["check_in"]),
                               tu.parse(row["check_out"]) if row["check_out"] else tu.now())


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
    key = f"w:{request.client.host if request.client else '?'}:{body.code.upper()}"
    _throttle(key)
    w = db.execute("SELECT id, pin_hash, language FROM workers WHERE code=?", (body.code.strip().upper(),)).fetchone()
    if not verify_pin(body.pin, w["pin_hash"] if w else None):
        _fails.setdefault(key, []).append(time.time())
        raise HTTPException(401, "Wrong code or PIN")
    return {"token": make_token(w["id"], "worker"), "language": w["language"]}


@router.post("/auth/admin")
def login_admin(body: AdminLogin, request: Request):
    key = f"a:{request.client.host if request.client else '?'}"
    _throttle(key)
    if not hmac.compare_digest(body.password.encode(), settings.admin_password.encode()):
        _fails.setdefault(key, []).append(time.time())
        raise HTTPException(401, "Wrong password")
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


def _open_shift(db, wid):
    return db.execute("SELECT * FROM shifts WHERE worker_id=? AND check_out IS NULL ORDER BY id DESC",
                      (wid,)).fetchone()


@router.post("/shifts/check-in")
def check_in(body: CheckIn, claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    method = None
    if body.qr:
        parts = body.qr.split("|")
        ok = (len(parts) == 3 and parts[0] == "FS" and parts[1] == str(w["site_id"])
              and hmac.compare_digest(parts[2], w["qr_secret"]))
        if not ok:
            raise HTTPException(403, "This QR is not for your site")
        method = "qr"
    elif body.lat is not None and body.lng is not None and w["lat"] is not None:
        if _haversine_m(body.lat, body.lng, w["lat"], w["lng"]) > w["radius_m"]:
            raise HTTPException(403, "You are too far from the site")
        method = "location"
    else:
        raise HTTPException(400, "Scan the site QR or share your location")
    now = tu.now()
    open_ = _open_shift(db, w["id"])
    if open_:
        cin = tu.parse(open_["check_in"])
        if now - cin < timedelta(hours=20):
            raise HTTPException(409, "Already checked in")
        db.execute("UPDATE shifts SET check_out=?, auto_closed=1 WHERE id=?",
                   (tu.iso(cin + timedelta(hours=w["std_daily_hours"])), open_["id"]))
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
    if hrs > 20:
        raise HTTPException(409, "This shift is over 20 hours old and needs supervisor review before checkout")
    db.execute("UPDATE shifts SET check_out=? WHERE id=?", (tu.iso(now), open_["id"]))
    return {"status": "checked_out", "hours": round(hrs, 2),
            "overtime_hours": round(max(0, hrs - w["std_daily_hours"]), 2)}


@router.get("/shifts/mine")
def my_shifts(days: int = Query(14, ge=1, le=60), claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    rows = db.execute("SELECT * FROM shifts WHERE worker_id=? AND check_in>=? ORDER BY check_in DESC",
                      (w["id"], tu.iso(tu.now() - timedelta(days=days)))).fetchall()
    open_ = next((r for r in rows if not r["check_out"]), None)
    return {"on_shift": bool(open_), "since": open_["check_in"] if open_ else None,
            "std_hours": w["std_daily_hours"],
            "shifts": [{"check_in": r["check_in"], "check_out": r["check_out"], "hours": round(_hours(r), 2),
                        "overtime_hours": round(max(0, _hours(r) - w["std_daily_hours"]), 2)} for r in rows]}


# ---------- worker: payslip ----------
def _payslip(db, w, month: str) -> dict:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "month must be YYYY-MM")
    y, m = int(month[:4]), int(month[5:])
    off = timedelta(minutes=settings.tz_offset_min)
    start = datetime(y, m, 1, tzinfo=tu.UTC) - off
    end = (datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=tu.UTC)) - off
    rows = db.execute("SELECT check_in,check_out FROM shifts WHERE worker_id=? AND check_in>=? AND check_in<? "
                      "AND check_out IS NOT NULL", (w["id"], tu.iso(start), tu.iso(end))).fetchall()
    shifts = [(tu.parse(r["check_in"]), tu.parse(r["check_out"])) for r in rows]
    return payroll.compute_payslip(shifts, w["hourly_rate"], w["std_daily_hours"], w["ot_multiplier"],
                                   settings.tz_offset_min)


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
    dedupe = hmac.new(settings.secret_key.encode(), f"{w['id']}|{mid or 'site'}|{week}".encode(), hashlib.sha256).hexdigest()
    if db.execute("SELECT 1 FROM feedback WHERE dedupe_hash=?", (dedupe,)).fetchone():
        raise HTTPException(409, "You already sent this review this week")
    comment = body.comment.strip()
    db.execute("INSERT INTO feedback(site_id,manager_id,topic,rating,comment,sentiment,week,dedupe_hash) VALUES(?,?,?,?,?,?,?,?)",
               (w["site_id"], mid, "manager" if mid else "conditions", body.rating, comment,
                gemini.sentiment(comment, body.rating), week, dedupe))
    return {"status": "received"}


# ---------- worker: skill passport ----------
@router.get("/passport")
def passport(claims=Depends(worker_claims), db=Depends(get_db)):
    w = _me(db, claims)
    skills = [dict(r) for r in db.execute(
        "SELECT name,kind,issuer,issued_on,expires_on FROM skills WHERE worker_id=? ORDER BY issued_on DESC", (w["id"],))]
    tenure = db.execute("SELECT COUNT(*) c FROM shifts WHERE worker_id=? AND check_out IS NOT NULL", (w["id"],)).fetchone()["c"]
    return {"name": w["name"], "code": w["code"], "job_title": w["job_title"], "sector": w["sector"],
            "employer_site": w["site_name"], "joined_on": w["joined_on"], "verified_shifts": tenure, "skills": skills}


# ---------- admin ----------
@router.get("/admin/sites")
def admin_sites(_=Depends(admin_claims), db=Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT id,name,sector FROM sites ORDER BY sector,name")]


@router.get("/admin/sites/{site_id}/qr.svg")
def site_qr(site_id: int, _=Depends(admin_claims), db=Depends(get_db)):
    s = db.execute("SELECT id,qr_secret FROM sites WHERE id=?", (site_id,)).fetchone()
    if not s:
        raise HTTPException(404, "No such site")
    buf = io.BytesIO()
    segno.make(f"FS|{s['id']}|{s['qr_secret']}", error="m").save(buf, kind="svg", scale=8, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/admin/overview")
def overview(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    sec = _sector(sector)
    wf = workforce.compute_workforce(db, sec)
    f = " AND s.sector=?" if sec else ""
    a = (sec,) if sec else ()
    on_shift = db.execute("SELECT COUNT(*) c FROM shifts sh JOIN sites s ON s.id=sh.site_id "
                          "WHERE sh.check_out IS NULL" + f, a).fetchone()["c"]
    open_safety = db.execute("SELECT COUNT(*) c FROM safety_reports r JOIN sites s ON s.id=r.site_id "
                             "WHERE r.status!='resolved'" + f, a).fetchone()["c"]
    avg = db.execute("SELECT AVG(rating) r FROM feedback fb JOIN sites s ON s.id=fb.site_id "
                     "WHERE fb.manager_id IS NOT NULL" + f, a).fetchone()["r"]
    overdue = sum(_overdue(r["severity"], r["status"], r["created_at"]) for r in db.execute(
        "SELECT r.severity,r.status,r.created_at FROM safety_reports r JOIN sites s ON s.id=r.site_id "
        "WHERE r.status!='resolved'" + f, a))
    today = workforce.attendance_trend(db, sec, 1)[-1]
    return {"sector": sec or "all", "workers": len(wf), "on_shift_now": on_shift, "attendance_today_pct": today["pct"],
            "high_fatigue": sum(x["fatigue"]["level"] == "high" for x in wf),
            "high_attrition": sum(x["attrition"]["level"] == "high" for x in wf),
            "open_safety": open_safety, "overdue_safety": overdue, "avg_rating": round(avg, 2) if avg else None}


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
def admin_safety(sector: str | None = None, status: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    sec = _sector(sector)
    sql = ("SELECT r.id,r.category,r.severity,r.location,r.summary,r.description,r.status,r.admin_note,r.created_at,"
           "s.name site,s.sector,w.code worker FROM safety_reports r JOIN sites s ON s.id=r.site_id "
           "JOIN workers w ON w.id=r.worker_id WHERE 1=1")
    args: list = []
    if sec:
        sql += " AND s.sector=?"; args.append(sec)
    if status:
        sql += " AND r.status=?"; args.append(status)
    order = "CASE r.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, r.id DESC"
    rows = [dict(r) for r in db.execute(sql + " ORDER BY " + order + " LIMIT 100", args)]
    for r in rows:
        r["overdue"] = _overdue(r["severity"], r["status"], r["created_at"])
    return rows


class StatusIn(BaseModel):
    status: Literal["open", "acknowledged", "in_progress", "resolved"]
    admin_note: str | None = Field(None, max_length=300)


@router.patch("/admin/safety/{rid}")
def update_safety(rid: int, body: StatusIn, _=Depends(admin_claims), db=Depends(get_db)):
    cur = db.execute("UPDATE safety_reports SET status=?, admin_note=COALESCE(?,admin_note), updated_at=? WHERE id=?",
                     (body.status, body.admin_note, tu.iso(tu.now()), rid))
    if not cur.rowcount:
        raise HTTPException(404, "No such report")
    return {"id": rid, "status": body.status}


@router.get("/admin/feedback")
def feedback_summary(sector: str | None = None, _=Depends(admin_claims), db=Depends(get_db)):
    """Managers with fewer than 3 reviews are hidden so a single worker can't be identified."""
    sec = _sector(sector)
    sql = ("SELECT m.id,m.name,s.name site,s.sector,COUNT(*) n,AVG(fb.rating) avg_rating,AVG(fb.sentiment) sentiment "
           "FROM feedback fb JOIN managers m ON m.id=fb.manager_id JOIN sites s ON s.id=fb.site_id WHERE 1=1")
    args: list = []
    if sec:
        sql += " AND s.sector=?"; args.append(sec)
    out = []
    for r in db.execute(sql + " GROUP BY m.id HAVING COUNT(*)>=3 ORDER BY avg_rating", args):
        comments = [c["comment"] for c in db.execute(
            "SELECT comment FROM feedback WHERE manager_id=? AND comment!='' ORDER BY id DESC LIMIT 5", (r["id"],))]
        out.append({"manager": r["name"], "site": r["site"], "sector": r["sector"], "reviews": r["n"],
                    "avg_rating": round(r["avg_rating"], 2), "sentiment": round(r["sentiment"] or 0, 2),
                    "comments": comments})
    csql = ("SELECT s.name site,s.sector,COUNT(*) n,AVG(fb.rating) r,AVG(fb.sentiment) se FROM feedback fb "
            "JOIN sites s ON s.id=fb.site_id WHERE fb.topic='conditions'")
    if sec:
        csql += " AND s.sector=?"
    for r in db.execute(csql + " GROUP BY s.id HAVING COUNT(*)>=3", args):
        cm = [c["comment"] for c in db.execute(
            "SELECT comment FROM feedback WHERE topic='conditions' AND comment!='' AND site_id=(SELECT id FROM sites WHERE name=?) "
            "ORDER BY id DESC LIMIT 5", (r["site"],))]
        out.append({"manager": "Working conditions (whole site)", "site": r["site"], "sector": r["sector"],
                    "reviews": r["n"], "avg_rating": round(r["r"], 2), "sentiment": round(r["se"] or 0, 2), "comments": cm})
    return out


class SkillIn(BaseModel):
    worker_code: str = Field(max_length=20)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["training", "certification", "experience"]
    issuer: str | None = Field(None, max_length=80)
    issued_on: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_on: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


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
    agg = {"sector": sec or "all", "workers": len(wf),
           "high_fatigue": sum(x["fatigue"]["level"] == "high" for x in wf),
           "high_quit_risk": sum(x["attrition"]["level"] == "high" for x in wf),
           "top_reasons": sorted({r for x in wf for r in x["attrition"]["reasons"]})[:5]}
    text = gemini.insights(agg)
    if not text:
        text = (f"{agg['high_fatigue']} of {agg['workers']} workers show high fatigue: cap overtime and enforce "
                f"11-hour rest gaps. {agg['high_quit_risk']} are at high quit risk: hold stay-conversations, "
                "resolve open safety reports and review low-rated managers.")
    return {"ai": gemini.available(), "text": text, "aggregate": agg}
