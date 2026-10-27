"""Pure payroll logic: daily overtime + simple statutory deductions (illustrative rates)."""
from collections import defaultdict
from datetime import datetime, timedelta

PF_RATE = 0.12          # on basic pay
ESI_RATE = 0.0075       # employee share, only if gross <= ESI_LIMIT
ESI_LIMIT = 21000.0


def shift_hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600)


def compute_payslip(shifts: list[tuple[datetime, datetime]], rate: float,
                    std_hours: float, ot_mult: float, tz_min: int) -> dict:
    """Overtime = hours beyond `std_hours` on the same local calendar day."""
    per_day: dict = defaultdict(float)
    for s, e in shifts:
        per_day[(s + timedelta(minutes=tz_min)).date()] += shift_hours(s, e)
    regular = sum(min(h, std_hours) for h in per_day.values())
    overtime = sum(max(0.0, h - std_hours) for h in per_day.values())
    basic = regular * rate
    ot_pay = overtime * rate * ot_mult
    gross = basic + ot_pay
    pf = basic * PF_RATE
    esi = gross * ESI_RATE if gross <= ESI_LIMIT else 0.0
    r = lambda x: round(x, 2)  # noqa: E731
    return {"days_worked": len(per_day), "regular_hours": r(regular), "overtime_hours": r(overtime),
            "rate": r(rate), "basic_pay": r(basic), "overtime_pay": r(ot_pay), "gross": r(gross),
            "pf": r(pf), "esi": r(esi), "net": r(gross - pf - esi)}
