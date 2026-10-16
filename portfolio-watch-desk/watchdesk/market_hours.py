"""US equity market sessions (NYSE/Nasdaq), in New York time."""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - systems without tz data (e.g. Windows without tzdata)
    _NY = None

HOLIDAYS = {
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
    date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
}
EARLY_CLOSE = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}  # 1:00 pm close

PRE_OPEN, OPEN, CLOSE, POST_CLOSE = dtime(4, 0), dtime(9, 30), dtime(16, 0), dtime(20, 0)


def _us_dst(utc: datetime) -> bool:
    """US daylight time: 2nd Sunday of March 2am to 1st Sunday of November 2am (local)."""
    y = utc.year
    march = datetime(y, 3, 8, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7, hours=7)  # 2am EST = 7am UTC
    nov = datetime(y, 11, 1, tzinfo=timezone.utc)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7, hours=6)  # 2am EDT = 6am UTC
    return start <= utc < end


def to_ny(ts: Optional[float] = None) -> datetime:
    utc = datetime.fromtimestamp(ts if ts is not None else datetime.now(timezone.utc).timestamp(), tz=timezone.utc)
    if _NY is not None:
        return utc.astimezone(_NY)
    off = -4 if _us_dst(utc) else -5
    return utc.astimezone(timezone(timedelta(hours=off)))


def is_crypto(symbol: str) -> bool:
    return symbol.upper().endswith(("-USD", "-USDT", "-EUR")) and "=" not in symbol


def session(ts: Optional[float] = None) -> str:
    """'open', 'pre', 'post' or 'closed' for US equities at time ts."""
    ny = to_ny(ts)
    d, t = ny.date(), ny.time()
    if ny.weekday() >= 5 or d in HOLIDAYS:
        return "closed"
    close = dtime(13, 0) if d in EARLY_CLOSE else CLOSE
    if OPEN <= t < close:
        return "open"
    if PRE_OPEN <= t < OPEN:
        return "pre"
    if close <= t < POST_CLOSE:
        return "post"
    return "closed"


def next_open(ts: Optional[float] = None) -> datetime:
    ny = to_ny(ts)
    d = ny.date()
    if ny.time() >= OPEN:
        d += timedelta(days=1)
    while d.weekday() >= 5 or d in HOLIDAYS:
        d += timedelta(days=1)
    return ny.replace(year=d.year, month=d.month, day=d.day, hour=9, minute=30, second=0, microsecond=0)


def poll_interval(intervals: dict, ts: Optional[float] = None, has_crypto: bool = False) -> float:
    """Seconds between polls for the current session."""
    s = session(ts)
    base = float(intervals.get(s, intervals.get("closed", 300)))
    if has_crypto:
        base = min(base, float(intervals.get("crypto", 30)))
    return max(base, 5.0)
