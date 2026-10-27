"""Explainable, rule-based fatigue and attrition scoring (no black box: every flag has a reason)."""
from datetime import datetime, timedelta

from ..timeutil import local_date

# --- fatigue rules (hours / days) and the score each triggered flag adds ---
WEEK_HOURS_HIGH = 60
WEEK_HOURS_ELEVATED = 48
LONG_SHIFT_HOURS = 12
MIN_REST_HOURS = 11
STREAK_DAYS = 7
FATIGUE_POINTS = {"WEEKLY_OVER_60": 45, "WEEKLY_OVER_48": 30, "LONG_SHIFT": 20, "BACK_TO_BACK": 25, "NO_REST_DAY": 25}
FATIGUE_TEXT = {
    "WEEKLY_OVER_48": "More than 48 hours worked in the last 7 days",
    "WEEKLY_OVER_60": "More than 60 hours worked in the last 7 days",
    "LONG_SHIFT": "At least one shift longer than 12 hours",
    "BACK_TO_BACK": "Less than 11 hours of rest between shifts",
    "NO_REST_DAY": "7 or more days worked in a row",
}

# --- attrition rules ---
ATTENDANCE_MIN_PRIOR_DAYS = 5
ATTENDANCE_DROP_RATIO = 0.6
NEW_JOINER_DAYS = 180
LOW_MANAGER_RATING = 3
FATIGUE_WEIGHT = 0.3
ATTRITION_POINTS = {"ATTENDANCE_DROP": 30, "NEW_JOINER": 15, "UNRESOLVED_SAFETY": 15, "LOW_MANAGER_RATING": 20}
ATTRITION_TEXT = {
    "ATTENDANCE_DROP": "Attendance fell sharply versus the previous two weeks",
    "HIGH_FATIGUE": "High fatigue score",
    "NEW_JOINER": "Joined less than 6 months ago",
    "UNRESOLVED_SAFETY": "Has a safety report unresolved for over 7 days",
    "LOW_MANAGER_RATING": "Their manager's anonymous rating is below 3/5",
}

Shift = tuple[datetime, datetime]


def level(score: int, high: int = 60, medium: int = 30) -> str:
    return "high" if score >= high else "medium" if score >= medium else "low"


def _hours_within(shifts: list[Shift], lo: datetime, hi: datetime) -> float:
    """Hours of the given shifts that overlap [lo, hi]."""
    total = 0.0
    for start, end in shifts:
        overlap = min(end, hi) - max(start, lo)
        if overlap.total_seconds() > 0:
            total += overlap.total_seconds() / 3600
    return total


def _has_short_rest(shifts: list[Shift]) -> bool:
    ordered = sorted(shifts)
    min_rest = timedelta(hours=MIN_REST_HOURS)
    return any(nxt[0] - prev[1] < min_rest for prev, nxt in zip(ordered, ordered[1:]))


def _longest_streak(shifts: list[Shift], tz_min: int) -> int:
    """Longest run of consecutive local calendar days with a shift start."""
    best = run = 0
    prev = None
    for day in sorted({local_date(start, tz_min) for start, _ in shifts}):
        run = run + 1 if prev and (day - prev).days == 1 else 1
        best, prev = max(best, run), day
    return best


def fatigue(shifts: list[Shift], now: datetime, tz_min: int) -> dict:
    """`shifts` are (start, end) in UTC; open shifts should be passed with end=now."""
    week_hours = _hours_within(shifts, now - timedelta(days=7), now)
    flags = []
    if week_hours > WEEK_HOURS_HIGH:
        flags.append("WEEKLY_OVER_60")
    elif week_hours > WEEK_HOURS_ELEVATED:
        flags.append("WEEKLY_OVER_48")
    if any(end - start > timedelta(hours=LONG_SHIFT_HOURS) for start, end in shifts):
        flags.append("LONG_SHIFT")
    if _has_short_rest(shifts):
        flags.append("BACK_TO_BACK")
    if _longest_streak(shifts, tz_min) >= STREAK_DAYS:
        flags.append("NO_REST_DAY")
    score = min(100, sum(FATIGUE_POINTS[f] for f in flags))
    return {"score": score, "level": level(score), "week_hours": round(week_hours, 1),
            "flags": flags, "reasons": [FATIGUE_TEXT[f] for f in flags]}


def attrition(fatigue_score: int, recent_days: int, prior_days: int, tenure_days: int,
              unresolved_reports: int, manager_rating: float | None) -> dict:
    codes = []
    if prior_days >= ATTENDANCE_MIN_PRIOR_DAYS and recent_days < prior_days * ATTENDANCE_DROP_RATIO:
        codes.append("ATTENDANCE_DROP")
    if fatigue_score >= 60:
        codes.append("HIGH_FATIGUE")
    if tenure_days < NEW_JOINER_DAYS:
        codes.append("NEW_JOINER")
    if unresolved_reports:
        codes.append("UNRESOLVED_SAFETY")
    if manager_rating is not None and manager_rating < LOW_MANAGER_RATING:
        codes.append("LOW_MANAGER_RATING")
    score = min(100, round(fatigue_score * FATIGUE_WEIGHT) + sum(ATTRITION_POINTS.get(c, 0) for c in codes))
    return {"score": score, "level": level(score, 55, 30), "reasons": [ATTRITION_TEXT[c] for c in codes]}
