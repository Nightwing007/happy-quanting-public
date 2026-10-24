"""Is a market open right now, and when does it next open or close?

Built on exchange_calendars (real holiday and half-day schedules, lunch breaks). Time always
comes from `clock.now()`. Past the end of what the calendar knows (it only has Indian holidays
about a year ahead) the answer is "unknown", and unknown allows trading: refusing orders for a
whole year because a holiday list ran out would be worse than the rare order on a holiday.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from app import clock
from app.trading.markets import Market

State = Literal["open", "closed", "unknown"]
ALWAYS_OPEN = "24/7"


@dataclass(frozen=True)
class MarketStatus:
    state: State
    is_open: bool
    session_open: datetime | None  # when today's (or the current) session began; None if not open
    next_open: datetime | None
    next_close: datetime | None
    timezone: str  # IANA name; the zone every label is shown in
    reason: str = ""  # why it is closed: "weekend", "holiday", "lunch break", "before the open"...


@cache
def _calendar(code: str):
    # Building a calendar takes tens of milliseconds, so each is built once.
    return xcals.get_calendar(code)


def timezone_of(market: Market) -> str:
    """IANA zone of the exchange; crypto is UTC."""
    if market.calendar == ALWAYS_OPEN:
        return "UTC"
    return str(_calendar(market.calendar).tz)


def _local(ts: pd.Timestamp, tz: str) -> datetime:
    return ts.to_pydatetime().astimezone(ZoneInfo(tz))


def _maybe(fn, *args) -> pd.Timestamp | None:
    try:
        return fn(*args)
    except ValueError:  # the calendar's out-of-bounds errors all subclass it
        return None  # asked about a moment beyond the calendar's end


def session_bounds(market: Market, day: date) -> tuple[datetime, datetime] | None:
    """(open, close) as UTC datetimes of the session the exchange held on its local date `day`,
    or None when it held none (weekend, holiday, or a date beyond the calendar).

    Crypto trades round the clock: its day runs from 00:00 UTC to 24:00 UTC, with the close put
    one second early so that it comes strictly before the next day's open. The replay tells two
    prices apart by the moment they existed, and a close stamped exactly on the next open would
    be indistinguishable from it.
    """
    if market.calendar == ALWAYS_OPEN:
        start = datetime.combine(day, time(0), tzinfo=UTC)
        return start, start + timedelta(days=1, seconds=-1)
    cal = _calendar(market.calendar)
    session = pd.Timestamp(day)
    if session < cal.first_session or session > cal.last_session or not cal.is_session(session):
        return None
    return cal.session_open(session).to_pydatetime(), cal.session_close(session).to_pydatetime()


def market_status(market: Market, at: datetime | None = None) -> MarketStatus:
    at = at or clock.now()
    if market.calendar == ALWAYS_OPEN:
        return MarketStatus("open", True, None, None, None, "UTC")

    cal = _calendar(market.calendar)
    tz = str(cal.tz)
    ts = pd.Timestamp(at)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    ts = ts.floor("min")  # calendars work in whole minutes

    if ts < cal.first_minute or ts > cal.last_minute:
        return MarketStatus("unknown", False, None, None, None, tz, "beyond the calendar")

    if cal.is_open_on_minute(ts):
        session = cal.minute_to_session(ts)
        break_start = cal.session_break_start(session)
        next_close = break_start if pd.notna(break_start) and ts < break_start else cal.session_close(session)
        return MarketStatus(
            "open", True, _local(cal.session_open(session), tz), None, _local(next_close, tz), tz
        )

    local_date = ts.tz_convert(tz).normalize().tz_localize(None)
    if cal.is_session(local_date):
        opens = cal.session_open(local_date)
        break_start = cal.session_break_start(local_date)
        break_end = cal.session_break_end(local_date)
        if ts < opens:
            reason, next_open = "before the open", opens
        elif pd.notna(break_start) and break_start <= ts < break_end:
            reason, next_open = "lunch break", break_end
        else:
            reason, next_open = "after the close", _maybe(cal.next_open, ts)
    else:
        reason = "weekend" if local_date.weekday() >= 5 else "holiday"
        next_open = _maybe(cal.next_open, ts)
    next_close = _maybe(cal.next_close, ts)
    return MarketStatus(
        "closed",
        False,
        None,
        _local(next_open, tz) if next_open is not None else None,
        _local(next_close, tz) if next_close is not None else None,
        tz,
        reason,
    )


def is_open(market: Market, at: datetime | None = None) -> bool:
    """Whether orders may fill. "Unknown" counts as open: see the module docstring."""
    return market_status(market, at).state != "closed"


def can_fill(market: Market, quote_as_of: int, at: datetime | None = None) -> bool:
    """Whether an order can fill against a quote stamped `quote_as_of` (unix seconds).

    The market must be open and the quote must be from the current session. Right after an
    open, delayed data still shows yesterday's close, and filling on it would be filling at a
    stale price.
    """
    status = market_status(market, at)
    if status.state == "closed":
        return False
    if status.session_open is None:  # unknown, or crypto: no session start to compare with
        return True
    return quote_as_of >= status.session_open.timestamp()


def _clock_text(moment: datetime, tz: str, now: datetime) -> str:
    local = moment.astimezone(ZoneInfo(tz))
    text = f"{local:%H:%M} {local:%Z}"
    if local.date() != now.astimezone(ZoneInfo(tz)).date():
        text = f"{local:%a} {text}"
    return text


def status_label(market: Market, status: MarketStatus, at: datetime | None = None) -> str:
    """Human text in the exchange's own timezone, e.g. "Market closed · opens Mon 09:15 IST"."""
    now = at or clock.now()
    if market.calendar == ALWAYS_OPEN:
        return "Open 24/7"
    if status.state == "unknown":
        return "Hours unknown"
    if status.is_open:
        if status.next_close is None:
            return "Market open"
        return f"Market open · closes {_clock_text(status.next_close, status.timezone, now)}"
    head = "Lunch break" if status.reason == "lunch break" else "Market closed"
    if status.next_open is None:
        return head
    verb = "reopens" if status.reason == "lunch break" else "opens"
    return f"{head} · {verb} {_clock_text(status.next_open, status.timezone, now)}"
