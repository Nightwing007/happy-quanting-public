"""A market data provider that replays the past.

It holds bars loaded up front and a movable `cursor` (the simulation clock). Everything it
answers is what a trader standing at the cursor could have seen, never a bar from after it.
"""

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .base import (
    Bar,
    DataUnavailable,
    Fundamentals,
    Instrument,
    MarketDataError,
    MarketDataProvider,
    Quote,
)

_DAILY_PLUS = {"1d", "1wk", "1mo"}
_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
_SECONDS |= {"1d": 86400, "1wk": 604800, "1mo": 2592000}  # a month is only a tie-break size here
_RANGE_DAYS = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366}
_RANGE_DAYS |= {"2y": 731, "5y": 1827, "10y": 3653}


def _midnight(day: date) -> int:
    return int(datetime.combine(day, time(0), tzinfo=UTC).timestamp())


def _span(bar: Bar, interval: str) -> tuple[int, int]:
    """(start, end) of a bar in UTC unix seconds.

    The end is the start plus the interval, because a bar's close is not known until the bar
    has finished: at 10:00:30 the 10:00 one-minute bar is still forming, so only the 09:59 bar
    may be used. A daily bar is stamped at its date's UTC midnight and ends 24 hours later, which
    is conservative (a daily close shows up a little late, never early); a month ends on the 1st.
    """
    if interval not in _DAILY_PLUS:
        start = int(bar.time)
        return start, start + _SECONDS[interval]
    day = date.fromisoformat(str(bar.time))
    start = _midnight(day)
    if interval == "1mo":
        return start, _midnight((day.replace(day=1) + timedelta(days=32)).replace(day=1))
    return start, start + _SECONDS[interval]


def bar_span(bar: Bar, interval: str) -> tuple[int, int]:
    """(start, end) of a bar in UTC unix seconds. The end is when its close becomes known: the
    moment a replay may first reveal it."""
    return _span(bar, interval)


SessionBounds = Callable[[date], tuple[datetime, datetime] | None]


def _session_span(bar: Bar, interval: str, sessions: SessionBounds) -> tuple[int, int] | None:
    """(session open, session close) of a daily-or-longer bar in UTC unix seconds, or None when
    the exchange had no session in its period (the caller then falls back to `_span`).

    A daily bar is one day's trading, not a price stamped at midnight: a trader could act on its
    open from the morning bell and on its close from the closing bell. A weekly or monthly bar
    opens with the first session of its period and closes with the last.
    """
    day = date.fromisoformat(str(bar.time))
    if interval == "1d":
        days = [day]
    elif interval == "1wk":
        days = [day + timedelta(days=i) for i in range(7)]
    else:
        first = day.replace(day=1)
        length = ((first + timedelta(days=32)).replace(day=1) - first).days
        days = [first + timedelta(days=i) for i in range(length)]
    held = [(d, sessions(d)) for d in days]
    held = [(d, bounds) for d, bounds in held if bounds is not None]
    if not held:
        return None
    return int(held[0][1][0].timestamp()), int(held[-1][1][1].timestamp())


@dataclass
class _Series:
    symbol: str
    interval: str
    bars: list[Bar]
    starts: list[int]
    ends: list[int]
    # Set for a daily-or-longer series whose exchange hours are known: when each bar's session
    # opened, so its open price can be quoted from then on. None where only the date is known.
    opens: list[int] | None = None

    def closed(self, at: int) -> int:
        """How many bars have ended by `at` (a bar ending exactly at `at` has)."""
        return bisect_right(self.ends, at)


class ReplayProvider:
    name = "replay"

    def __init__(
        self,
        cursor: datetime,
        *,
        instruments: Mapping[str, Instrument] | None = None,
        inner: MarketDataProvider | None = None,
        timezones: Mapping[str, str] | None = None,
        sessions: Mapping[str, SessionBounds] | None = None,
    ):
        """`cursor` is the replayed "now" (aware) and may be reassigned at any time.

        `instruments` (or else `inner`) supplies name, exchange, type and currency; `inner` is
        never asked for a price. `timezones` maps a symbol to its exchange zone: it makes
        `get_bars` time stamps exchange-local like the live provider's, and decides what
        "the prior session" means for `previous_close`. Unlisted symbols are read as UTC.

        `sessions` maps a symbol to a function giving the (open, close) of its exchange session on
        a date, or None for a day with none. With it, a daily bar is not one price at midnight but
        two: its open is quoted from the session open and its close from the session close (see
        `_session_span`). Without it a daily bar is stamped at UTC midnight and ends 24 hours on.
        """
        self.cursor = cursor
        self._instruments = dict(instruments or {})
        self._inner = inner
        self._timezones = dict(timezones or {})
        self._sessions = dict(sessions or {})
        self._series: dict[str, dict[str, _Series]] = {}

    def load(self, symbol: str, interval: str, bars: Sequence[Bar]) -> None:
        """Add bars, in the form `history.get_history` returns them. An FX pair is loaded
        like any symbol: intraday bars are replayed like a stock's, daily bars serve as the
        nearest earlier daily close."""
        if interval not in _SECONDS:
            raise MarketDataError(f"The replay can't hold {interval} bars.")
        sessions = self._sessions.get(symbol) if interval in _DAILY_PLUS else None
        if sessions is None:
            ordered = sorted(bars, key=lambda b: _span(b, interval)[0])
            spans = [_span(b, interval) for b in ordered]
            opens = None
        else:
            found = sorted(((_session_span(b, interval, sessions) or _span(b, interval), b) for b in bars),
                           key=lambda pair: pair[0][0])  # fmt: skip
            ordered = [b for _, b in found]
            spans = [span for span, _ in found]
            opens = [s for s, _ in spans]
        self._series.setdefault(symbol, {})[interval] = _Series(
            symbol, interval, ordered, [s for s, _ in spans], [e for _, e in spans], opens
        )

    def _at(self) -> int:
        if self.cursor.tzinfo is None:
            raise ValueError("The replay cursor must be timezone-aware")
        return int(self.cursor.timestamp())

    def _zone(self, symbol: str) -> ZoneInfo:
        return ZoneInfo(self._timezones.get(symbol, "UTC"))

    def _details(self, symbol: str) -> Instrument:
        found = self._instruments.get(symbol)
        if found is None and self._inner is not None:
            quote = self._inner.get_quote(symbol)  # for the name and currency only
            found = Instrument(symbol, quote.name, quote.exchange, quote.type, quote.currency)
            self._instruments[symbol] = found
        if found is None:
            raise DataUnavailable(f"The replay has no instrument details for {symbol}.")
        return found

    def _session_day(self, series: _Series, index: int) -> date:
        if series.interval in _DAILY_PLUS:
            return date.fromisoformat(str(series.bars[index].time))
        return datetime.fromtimestamp(series.starts[index], self._zone(series.symbol)).date()

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        if self._inner is None:
            raise MarketDataError("The replay can't search: it only holds the symbols loaded into it.")
        return self._inner.search(query, limit)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        # Today's figures, not the replayed day's: fine for a profile card, never for a decision.
        if self._inner is None:
            raise MarketDataError("The replay has no fundamentals.")
        return self._inner.get_fundamentals(symbol)

    def get_quote(self, symbol: str) -> Quote:
        by_interval = self._series.get(symbol)
        if not by_interval:
            raise DataUnavailable(f"The replay has no data loaded for {symbol}.")
        at = self._at()
        # The freshest price wins, finer on a tie: with intraday bars loaded the quote moves every
        # bar, and where only daily bars exist (an FX pair) it is the nearest earlier close. A
        # daily bar with known session hours has two prices: its open from the opening bell until
        # the close, then its close.
        best: tuple[int, int, _Series, int, bool] | None = None
        for series in by_interval.values():
            count = series.closed(at)
            found = []
            if count:
                found.append((series.ends[count - 1], count - 1, False))
            if series.opens is not None:
                started = bisect_right(series.opens, at)
                if started > count:  # this session has opened and not yet closed
                    found.append((series.opens[started - 1], started - 1, True))
            for as_of, index, at_open in found:
                key = (as_of, -_SECONDS[series.interval])
                if best is None or key > best[:2]:
                    best = (*key, series, index, at_open)
        if best is None:
            raise DataUnavailable(f"No {symbol} bar has closed yet at {self.cursor:%Y-%m-%d %H:%M %Z}.")
        as_of, _, series, index, at_open = best

        today = self._session_day(series, index)
        previous = None
        for back in range(index - 1, -1, -1):
            if self._session_day(series, back) < today:
                previous = series.bars[back].close
                break
        info = self._details(symbol)
        bar = series.bars[index]
        return Quote(
            symbol=symbol,
            name=info.name,
            exchange=info.exchange,
            type=info.type,
            currency=info.currency,
            price=bar.open if at_open else bar.close,
            previous_close=previous,
            as_of=as_of,  # when the price existed, so hours.can_fill sees a fresh quote
        )

    def _emit(self, symbol: str, series: _Series, indexes: Sequence[int]) -> list[Bar]:
        out = []
        for i in indexes:
            bar = series.bars[i]
            if series.interval not in _DAILY_PLUS:
                # Same exchange-local stamping as the live provider, so charts read alike.
                local = datetime.fromtimestamp(series.starts[i], self._zone(symbol))
                offset = int(local.utcoffset().total_seconds())
                bar = Bar(int(bar.time) + offset, bar.open, bar.high, bar.low, bar.close, bar.volume)
            out.append(bar)
        return out

    def get_bars(self, symbol: str, interval: str, range_: str) -> list[Bar]:
        series = self._series.get(symbol, {}).get(interval)
        if series is None:
            raise DataUnavailable(f"The replay has no {interval} bars loaded for {symbol}.")
        at = self._at()
        count = series.closed(at)  # nothing that ends after the cursor, ever
        floor = None
        if range_ == "ytd":
            floor = _midnight(date(self.cursor.astimezone(UTC).year, 1, 1))
        elif range_ in _RANGE_DAYS:
            floor = at - _RANGE_DAYS[range_] * 86400
        return self._emit(
            symbol, series, [i for i in range(count) if floor is None or series.starts[i] >= floor]
        )

    def recent_bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        """The last `n` closed bars, oldest first: `get_bars` without building the whole past on
        every call, which is what makes a long backtest linear instead of quadratic."""
        series = self._series.get(symbol, {}).get(interval)
        if series is None:
            raise DataUnavailable(f"The replay has no {interval} bars loaded for {symbol}.")
        count = series.closed(self._at())
        return self._emit(symbol, series, range(max(0, count - n), count))

    def visit_times(self, symbols: Sequence[str], interval: str) -> list[int]:
        """Every moment worth moving the cursor to, ascending: when a bar of `interval` closes,
        and for a daily-or-longer bar with known hours also when its session opens."""
        moments: set[int] = set()
        for symbol in symbols:
            series = self._series.get(symbol, {}).get(interval)
            if series is None:
                continue
            moments.update(series.ends)
            if series.opens is not None:
                moments.update(series.opens)
        return sorted(moments)

    def close_times(self, symbols: Sequence[str], interval: str) -> set[int]:
        """The moments at which a bar of `interval` closes (a subset of `visit_times`)."""
        out: set[int] = set()
        for symbol in symbols:
            series = self._series.get(symbol, {}).get(interval)
            if series is not None:
                out.update(series.ends)
        return out

    def first_cursor(self, symbols: Sequence[str], interval: str) -> datetime | None:
        """Where to start a replay so that nothing has happened yet: the start of the first bar,
        or one second before the first session open, whose open price is already a quote."""
        starts = []
        for symbol in symbols:
            series = self._series.get(symbol, {}).get(interval)
            if series is not None and series.starts:
                starts.append(series.starts[0] - (1 if series.opens is not None else 0))
        return datetime.fromtimestamp(min(starts), UTC) if starts else None

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        series = self._series.get(symbol, {}).get(interval)
        if series is None:
            raise DataUnavailable(f"The replay has no {interval} bars loaded for {symbol}.")
        count = series.closed(self._at())
        lo, hi = _midnight(start), _midnight(end + timedelta(days=1))
        return [series.bars[i] for i in range(count) if lo <= series.starts[i] < hi]
