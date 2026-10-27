"""Explainable, rule-based fatigue and attrition scoring (no black box: every flag has a reason)."""
from datetime import datetime, timedelta

from ..timeutil import local_date

FATIGUE_TEXT = {
    "WEEKLY_OVER_48": "More than 48 hours worked in the last 7 days",
    "WEEKLY_OVER_60": "More than 60 hours worked in the last 7 days",
    "LONG_SHIFT": "At least one shift longer than 12 hours",
    "BACK_TO_BACK": "Less than 11 hours of rest between shifts",
    "NO_REST_DAY": "7 or more days worked in a row",
}
ATTRITION_TEXT = {
    "ATTENDANCE_DROP": "Attendance fell sharply versus the previous two weeks",
    "HIGH_FATIGUE": "High fatigue score",
    "NEW_JOINER": "Joined less than 6 months ago",
    "UNRESOLVED_SAFETY": "Has a safety report unresolved for over 7 days",
    "LOW_MANAGER_RATING": "Their manager's anonymous rating is below 3/5",
}


def level(score: int, high: int = 60, medium: int = 30) -> str:
    return "high" if score >= high else "medium" if score >= medium else "low"


def fatigue(shifts: list[tuple[datetime, datetime]], now: datetime, tz_min: int) -> dict:
    """`shifts` are (start, end) in UTC; open shifts should be passed with end=now."""
    week_start = now - timedelta(days=7)
    week_hours = 0.0
    for s, e in shifts:
        lo, hi = max(s, week_start), min(e, now)
        if hi > lo:
            week_hours += (hi - lo).total_seconds() / 3600
    flags, score = [], 0
    if week_hours > 60:
        flags.append("WEEKLY_OVER_60"); score += 45
    elif week_hours > 48:
        flags.append("WEEKLY_OVER_48"); score += 30
    if any((e - s).total_seconds() > 12 * 3600 for s, e in shifts):
        flags.append("LONG_SHIFT"); score += 20
    ordered = sorted(shifts)
    if any((b[0] - a[1]).total_seconds() < 11 * 3600 for a, b in zip(ordered, ordered[1:])):
        flags.append("BACK_TO_BACK"); score += 25
    days = sorted({local_date(s, tz_min) for s, _ in shifts})
    run = best = 0
    prev = None
    for d in days:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best, prev = max(best, run), d
    if best >= 7:
        flags.append("NO_REST_DAY"); score += 25
    score = min(100, score)
    return {"score": score, "level": level(score), "week_hours": round(week_hours, 1),
            "flags": flags, "reasons": [FATIGUE_TEXT[f] for f in flags]}


def attrition(fatigue_score: int, recent_days: int, prior_days: int, tenure_days: int,
              unresolved_reports: int, manager_rating: float | None) -> dict:
    score, codes = 0, []
    if prior_days >= 5 and recent_days < prior_days * 0.6:
        score += 30; codes.append("ATTENDANCE_DROP")
    score += round(fatigue_score * 0.3)
    if fatigue_score >= 60:
        codes.append("HIGH_FATIGUE")
    if tenure_days < 180:
        score += 15; codes.append("NEW_JOINER")
    if unresolved_reports:
        score += 15; codes.append("UNRESOLVED_SAFETY")
    if manager_rating is not None and manager_rating < 3:
        score += 20; codes.append("LOW_MANAGER_RATING")
    score = min(100, score)
    return {"score": score, "level": level(score, 55, 30), "reasons": [ATTRITION_TEXT[c] for c in codes]}
