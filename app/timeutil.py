from datetime import datetime, timedelta, timezone

UTC = timezone.utc
FMT = "%Y-%m-%dT%H:%M:%SZ"


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT).replace(tzinfo=UTC)


def local_date(dt: datetime, tz_min: int):
    return (dt + timedelta(minutes=tz_min)).date()


def iso_week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"
