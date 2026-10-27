"""Payroll calculations with local-calendar-day overtime.

Rates in this module are illustrative configuration, not legal payroll advice.
"""
from collections import defaultdict
from datetime import datetime, timedelta

PF_RATE = 0.12          # illustrative employee contribution on basic pay
ESI_RATE = 0.0075       # illustrative employee share, only if gross <= ESI_LIMIT
ESI_LIMIT = 21000.0


def _r2(x: float) -> float:
    return round(x, 2)


def shift_hours(start: datetime, end: datetime) -> float:
    """Return non-negative elapsed hours; invalid/reversed intervals count as zero."""
    return max(0.0, (end - start).total_seconds() / 3600)


def _hours_by_local_day(start: datetime, end: datetime, tz_min: int) -> dict:
    """Split an interval at local midnight, retaining UTC-aware input timestamps."""
    daily = defaultdict(float)
    if end <= start:
        return daily
    offset = timedelta(minutes=tz_min)
    cursor = start
    while cursor < end:
        local_cursor = cursor + offset
        next_local_midnight = (local_cursor.replace(hour=0, minute=0, second=0, microsecond=0)
                               + timedelta(days=1))
        next_boundary_utc = next_local_midnight - offset
        segment_end = min(end, next_boundary_utc)
        if segment_end <= cursor:  # defensive guard against malformed timezone inputs
            break
        daily[local_cursor.date()] += (segment_end - cursor).total_seconds() / 3600
        cursor = segment_end
    return daily


def compute_payslip(shifts: list[tuple[datetime, datetime]], rate: float,
                    std_hours: float, ot_mult: float, tz_min: int) -> dict:
    """Calculate daily overtime after splitting overnight shifts at local midnight.

    This is a transparent demo calculation. Production payroll must use validated,
    jurisdiction-specific rules and approved contribution bases/rates.
    """
    if rate < 0 or std_hours <= 0 or ot_mult < 1:
        raise ValueError("rate must be non-negative, std_hours positive, and ot_mult >= 1")
    per_day: defaultdict = defaultdict(float)
    for start, end in shifts:
        if end < start:
            raise ValueError("shift end must not be before shift start")
        for day, hours in _hours_by_local_day(start, end, tz_min).items():
            per_day[day] += hours
    regular = sum(min(hours, std_hours) for hours in per_day.values())
    overtime = sum(max(0.0, hours - std_hours) for hours in per_day.values())
    basic = regular * rate
    ot_pay = overtime * rate * ot_mult
    gross = basic + ot_pay
    pf = basic * PF_RATE
    esi = gross * ESI_RATE if gross <= ESI_LIMIT else 0.0
    return {"days_worked": len(per_day), "regular_hours": _r2(regular), "overtime_hours": _r2(overtime),
            "rate": _r2(rate), "basic_pay": _r2(basic), "overtime_pay": _r2(ot_pay), "gross": _r2(gross),
            "pf": _r2(pf), "esi": _r2(esi), "net": _r2(gross - pf - esi)}
