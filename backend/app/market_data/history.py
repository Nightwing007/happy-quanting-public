"""Past bars, fetched once and kept.

`get_history` asks the provider only for days it has not already asked about, stores the bars
in `bar_cache`, and answers from there. `history_spans` remembers which days were asked, so a
weekend or holiday (which has no bars) is not asked again every time.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import BarCache, HistorySpan

from .base import ALLOWED_RANGES, Bar, MarketDataError, MarketDataProvider

_DAILY_PLUS = {"1d", "1wk", "1mo"}


class HistoryRangeError(MarketDataError):
    """The dates asked for are ones Yahoo cannot serve for that interval."""


@dataclass(frozen=True)
class IntervalLimit:
    lookback_days: int | None  # how far back from today Yahoo serves this interval; None: no limit
    chunk_days: int | None  # most days one request may cover; None: any span within the lookback
    stated_days: str  # the figure Yahoo states, for the message


# What Yahoo serves, by interval. Source: the yfinance documentation of `history()` ("intraday data
# cannot extend last 60 days"; 1h reaches back 730 days) and the errors Yahoo returns ("1m data
# ... only 8 days worth of 1m granularity data are allowed to be fetched per request" and "the
# requested range must be within the last 30 days"). Read from those texts; not re-checked against
# a live response. Yahoo measures from the current instant, not midnight, so each lookback is one
# day inside the stated figure; a request on the edge would otherwise fail at random. A 1m request
# is cut into 7-day chunks, so 30 days of minutes can be had even though one request holds only 7.
LIMITS: dict[str, IntervalLimit] = {
    "1m": IntervalLimit(29, 7, "30"),
    "5m": IntervalLimit(59, None, "60"),
    "15m": IntervalLimit(59, None, "60"),
    "30m": IntervalLimit(59, None, "60"),
    "1h": IntervalLimit(729, None, "730"),
    "1d": IntervalLimit(None, None, ""),
    "1wk": IntervalLimit(None, None, ""),
    "1mo": IntervalLimit(None, None, ""),
}


def today_utc() -> date:
    return clock.now().astimezone(UTC).date()


def earliest_date(interval: str, today: date) -> date | None:
    """The first day Yahoo serves for `interval`, or None when it has no limit."""
    limit = LIMITS[interval]
    return None if limit.lookback_days is None else today - timedelta(days=limit.lookback_days)


def history_limits(today: date | None = None) -> list[tuple[str, date | None]]:
    today = today or today_utc()
    return [(interval, earliest_date(interval, today)) for interval in ALLOWED_RANGES]


def _validate(interval: str, start: date, end: date, today: date) -> None:
    if interval not in LIMITS:
        raise HistoryRangeError(f"Interval '{interval}' isn't available. Choose one of: {', '.join(LIMITS)}.")
    if start > end:
        raise HistoryRangeError(f"The start date {start:%d %b %Y} is after the end date {end:%d %b %Y}.")
    if end > today:
        raise HistoryRangeError(
            f"There is no data after today ({today:%d %b %Y}); pick an end date on or before it."
        )
    earliest = earliest_date(interval, today)
    if earliest is not None and start < earliest:
        raise HistoryRangeError(
            f"{interval} bars only go back about {LIMITS[interval].stated_days} days: the earliest date "
            f"available is {earliest:%d %b %Y}. Pick a start on or after it."
        )


def validate_range(interval: str, start: date, end: date, today: date | None = None) -> None:
    """Refuse a range Yahoo can't serve, with the sentence `get_history` would raise."""
    _validate(interval, start, end, today or today_utc())


def _midnight(day: date) -> int:
    return int(datetime.combine(day, time(0), tzinfo=UTC).timestamp())


def _ts(bar: Bar, daily: bool) -> int:
    return _midnight(date.fromisoformat(str(bar.time))) if daily else int(bar.time)


def _to_bar(row: BarCache, daily: bool) -> Bar:
    when: str | int = datetime.fromtimestamp(row.ts, UTC).date().isoformat() if daily else row.ts
    return Bar(when, row.open, row.high, row.low, row.close, row.volume)


def _missing(spans: list[tuple[date, date]], start: date, end: date) -> list[tuple[date, date]]:
    """The parts of start..end (inclusive) that no recorded span covers."""
    gaps: list[tuple[date, date]] = []
    cursor = start
    for span_start, span_end in sorted(spans):
        if span_end < cursor:
            continue
        if span_start > end:
            break
        if span_start > cursor:
            gaps.append((cursor, span_start - timedelta(days=1)))
        cursor = max(cursor, span_end + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def _chunks(gap: tuple[date, date], chunk_days: int | None) -> list[tuple[date, date]]:
    if chunk_days is None:
        return [gap]
    out, cursor = [], gap[0]
    while cursor <= gap[1]:
        last = min(cursor + timedelta(days=chunk_days - 1), gap[1])
        out.append((cursor, last))
        cursor = last + timedelta(days=1)
    return out


def _record_span(db: Session, symbol: str, interval: str, start: date, end: date) -> None:
    rows = list(
        db.scalars(select(HistorySpan).where(HistorySpan.symbol == symbol, HistorySpan.interval == interval))
    )
    # Fold in every span that overlaps or touches the new one, so the table stays a few rows.
    one_day = timedelta(days=1)
    for row in rows:
        if row.start_date <= end + one_day and row.end_date >= start - one_day:
            start, end = min(start, row.start_date), max(end, row.end_date)
            db.delete(row)
    db.flush()  # the unique key must see the deletes before the merged row goes in
    db.add(HistorySpan(symbol=symbol, interval=interval, start_date=start, end_date=end))


def _store(db: Session, symbol: str, interval: str, bars: list[Bar], daily: bool) -> None:
    if not bars:
        return
    stamped = {_ts(b, daily): b for b in bars}
    existing = {
        row.ts: row
        for row in db.scalars(
            select(BarCache).where(
                BarCache.symbol == symbol,
                BarCache.interval == interval,
                BarCache.ts.between(min(stamped), max(stamped)),
            )
        )
    }
    for ts, bar in stamped.items():
        row = existing.get(ts)
        if row is None:
            db.add(
                BarCache(
                    symbol=symbol,
                    interval=interval,
                    ts=ts,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
        else:  # today's bars grow as the day goes on, so a refetch overwrites
            row.open, row.high, row.low, row.close, row.volume = (
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
            )


def get_history(
    db: Session,
    provider: MarketDataProvider,
    symbol: str,
    interval: str,
    start: date,
    end: date,
    today: date | None = None,
) -> list[Bar]:
    """Bars for start..end (calendar days, inclusive), oldest first.

    Intraday `Bar.time` is UTC unix seconds; daily and longer is "YYYY-MM-DD". The cache is keyed
    by UTC day, which holds the whole session of every market this app trades (the only exchanges
    whose session crosses UTC midnight are in Australasia).
    """
    today = today or today_utc()
    _validate(interval, start, end, today)
    daily = interval in _DAILY_PLUS
    limit = LIMITS[interval]

    spans = [
        (row.start_date, row.end_date)
        for row in db.scalars(
            select(HistorySpan).where(HistorySpan.symbol == symbol, HistorySpan.interval == interval)
        )
    ]
    # Today is never recorded as fetched: its bars are still arriving, so it is asked again.
    settled = today - timedelta(days=1)
    for gap in _missing(spans, start, end):
        for first, last in _chunks(gap, limit.chunk_days):
            _store(db, symbol, interval, provider.get_history(symbol, interval, first, last), daily)
            if first <= settled:
                _record_span(db, symbol, interval, first, min(last, settled))
            db.commit()  # per chunk, so a later failure keeps what was already fetched

    rows = db.scalars(
        select(BarCache)
        .where(
            BarCache.symbol == symbol,
            BarCache.interval == interval,
            BarCache.ts >= _midnight(start),
            BarCache.ts < _midnight(end + timedelta(days=1)),
        )
        .order_by(BarCache.ts)
    )
    return [_to_bar(row, daily) for row in rows]
