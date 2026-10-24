"""Offline, deterministic provider for tests and for running without network."""

import math
import random
import threading
import zlib
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app import clock

from .base import Bar, DataUnavailable, Fundamentals, Instrument, Quote, SymbolNotFound

# symbol, name, exchange, type, currency, base price
_SEED = [
    ("AAPL", "Apple Inc.", "NASDAQ", "equity", "USD", "230"),
    ("MSFT", "Microsoft Corporation", "NASDAQ", "equity", "USD", "420"),
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSE Arca", "etf", "USD", "560"),
    ("RELIANCE.NS", "Reliance Industries Limited", "NSE", "equity", "INR", "1250"),
    ("TCS.NS", "Tata Consultancy Services Limited", "NSE", "equity", "INR", "4100"),
    ("HDFCBANK.NS", "HDFC Bank Limited", "NSE", "equity", "INR", "1650"),
    ("RELIANCE.BO", "Reliance Industries Limited", "BSE", "equity", "INR", "1250"),
    ("VOD.L", "Vodafone Group Plc", "LSE", "equity", "GBP", "0.72"),
    ("SAP.DE", "SAP SE", "XETRA", "equity", "EUR", "200"),
    ("0700.HK", "Tencent Holdings Limited", "HKEX", "equity", "HKD", "380"),
    ("BTC-USD", "Bitcoin USD", "CCC", "crypto", "USD", "60000"),
    ("ETH-USD", "Ethereum USD", "CCC", "crypto", "USD", "2600"),
    ("^GSPC", "S&P 500", "SNP", "index", "USD", "5600"),
    ("^NSEI", "NIFTY 50", "NSE", "index", "INR", "24500"),
    # FX pairs are kept mutually consistent: 1 USD = 83.5 INR, EUR = 1.08 USD, GBP = 1.27 USD,
    # HKD = 0.128 USD. Add pairs here whenever a test needs a new market.
    ("USDINR=X", "USD/INR", "CCY", "currency", "INR", "83.5"),
    ("INRUSD=X", "INR/USD", "CCY", "currency", "USD", "0.011976"),
    ("EURUSD=X", "EUR/USD", "CCY", "currency", "USD", "1.08"),
    ("GBPUSD=X", "GBP/USD", "CCY", "currency", "USD", "1.27"),
    ("EURINR=X", "EUR/INR", "CCY", "currency", "INR", "90.18"),
    ("GBPINR=X", "GBP/INR", "CCY", "currency", "INR", "106.045"),
    ("HKDUSD=X", "HKD/USD", "CCY", "currency", "USD", "0.128"),
    ("HKDINR=X", "HKD/INR", "CCY", "currency", "INR", "10.688"),
]


def _fund(**fields: str | None) -> dict[str, Decimal | None]:
    return {k: None if v is None else Decimal(v) for k, v in fields.items()}


# Fixed company figures, in the units Fundamentals documents (ROE and yield in percent, D/E a ratio).
# TCS has no debt-to-equity on purpose, so tests can see a metric with no figure dropped rather
# than shown blank. Symbols not listed here (indexes, ETFs, FX) have no fundamentals at all.
_FUNDAMENTALS: dict[str, tuple[str | None, str | None, dict[str, Decimal | None]]] = {
    "AAPL": (
        "Technology",
        "Consumer Electronics",
        _fund(
            trailing_pe="24.8",
            price_to_book="8.45",
            return_on_equity="45.2",
            debt_to_equity="1.5",
            dividend_yield="0.45",
        ),
    ),
    "RELIANCE.NS": (
        "Energy",
        "Oil & Gas Refining & Marketing",
        _fund(
            trailing_pe="24.1",
            price_to_book="2.1",
            return_on_equity="9.8",
            debt_to_equity="0.38",
            dividend_yield="0.35",
            market_cap="17000000000000",
        ),
    ),
    "TCS.NS": (
        "Technology",
        "Information Technology Services",
        _fund(
            trailing_pe="30",
            price_to_book="12.4",
            return_on_equity="51.6",
            debt_to_equity=None,
            dividend_yield="1.6",
        ),
    ),
    "HDFCBANK.NS": (
        "Financial Services",
        "Banks - Regional",
        _fund(
            trailing_pe="18.2",
            price_to_book="2.6",
            return_on_equity="14.1",
            debt_to_equity="0.9",
            dividend_yield="1.1",
        ),
    ),
    # 52-week position: (60000 - 40000) / (75000 - 40000) = 20000 / 35000 = 57.14% of the way up.
    "BTC-USD": (
        None,
        None,
        _fund(
            market_cap="1200000000000",
            volume_24h="35000000000",
            circulating_supply="19800000",
            fifty_two_week_low="40000",
            fifty_two_week_high="75000",
        ),
    ),
}

_INTRADAY_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
_RANGE_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    "ytd": 200,
    "max": 3650,
}
_INTERVAL_STEP_DAYS = {"1d": 1, "1wk": 7, "1mo": 30}
_SESSION_MINUTES = 6 * 60  # intraday bars are generated over a short session, not 24 hours
_MAX_BARS = 400
# Fixed so history never depends on today's date.
_ANCHOR = datetime(2025, 1, 1, tzinfo=UTC)
_PRICE_STEP = Decimal("0.000001")

# Symbols with deterministic 1-minute history, over their real session: IANA zone, local open,
# length in minutes, and whether weekends are skipped. NSE 09:15-15:30 IST, US 09:30-16:00 ET,
# crypto round the clock. Holidays are not modelled.
_SESSIONS: dict[str, tuple[str, time, int, bool]] = {
    "RELIANCE.NS": ("Asia/Kolkata", time(9, 15), 375, True),
    "AAPL": ("America/New_York", time(9, 30), 390, True),
    "BTC-USD": ("UTC", time(0, 0), 1440, False),
}
_HISTORY_CHUNK_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self._instruments = {s: Instrument(s, n, e, t, c) for s, n, e, t, c, _ in _SEED}
        self._price = {row[0]: Decimal(row[5]) for row in _SEED}
        self._previous = {s: (p * Decimal("0.99")).quantize(_PRICE_STEP) for s, p in self._price.items()}
        # History is built from these, never from the movable `_price`, so a test that calls
        # set_price cannot change what a past day looked like.
        self._base = dict(self._price)
        self._as_of: dict[str, int] = {}
        self._lock = threading.Lock()

    def set_as_of(self, symbol: str, as_of: int) -> None:
        """Pin a symbol's quote time (unix seconds), e.g. to make it stale. Unset, quotes are
        stamped with the replaceable clock, so a test with a fixed clock gets fresh quotes."""
        self._require(symbol)
        with self._lock:
            self._as_of[symbol] = as_of

    def set_price(self, symbol: str, price: Decimal) -> None:
        # previous_close stays fixed so a test can move the price and see a stable day change.
        self._require(symbol)
        with self._lock:
            self._price[symbol] = Decimal(price)

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        needle = query.strip().lower()
        if not needle:
            return []
        hits = [
            i for i in self._instruments.values() if needle in i.symbol.lower() or needle in i.name.lower()
        ]
        return hits[:limit]

    def get_quote(self, symbol: str) -> Quote:
        inst = self._require(symbol)
        with self._lock:
            price, previous = self._price[symbol], self._previous[symbol]
            as_of = self._as_of.get(symbol)
        return Quote(
            symbol=inst.symbol,
            name=inst.name,
            exchange=inst.exchange,
            type=inst.type,
            currency=inst.currency,
            price=price,
            previous_close=previous,
            as_of=as_of if as_of is not None else int(clock.now().timestamp()),
        )

    def get_bars(self, symbol: str, interval: str, range_: str) -> list[Bar]:
        self._require(symbol)
        with self._lock:
            current = self._price[symbol]
        rng = random.Random(zlib.crc32(f"{symbol}:{interval}".encode()))

        times: list[str | int]
        if interval in _INTRADAY_MINUTES:
            minutes = _INTRADAY_MINUTES[interval]
            days = min(_RANGE_DAYS.get(range_, 1), 30)
            count = min(max(2, days * _SESSION_MINUTES // minutes), _MAX_BARS)
            step = timedelta(minutes=minutes)
            times = [int((_ANCHOR + step * k).timestamp()) for k in range(1 - count, 1)]
        else:
            step_days = _INTERVAL_STEP_DAYS.get(interval, 1)
            count = min(max(2, _RANGE_DAYS.get(range_, 30) // step_days), _MAX_BARS)
            times = [
                (_ANCHOR + timedelta(days=step_days * k)).strftime("%Y-%m-%d") for k in range(1 - count, 1)
            ]

        # Random walk generated backwards from the current price so the last close matches it.
        closes = [current]
        for _ in range(count - 1):
            move = Decimal(str(round(rng.uniform(-0.01, 0.01), 5)))
            closes.append(closes[-1] / (1 + move))
        closes.reverse()

        bars: list[Bar] = []
        for index, (when, close) in enumerate(zip(times, closes, strict=True)):
            wobble = Decimal(str(round(rng.uniform(-0.004, 0.004), 5)))
            open_ = (close * (1 + wobble)).quantize(_PRICE_STEP)
            close = current if index == count - 1 else close.quantize(_PRICE_STEP)
            high = (max(open_, close) * Decimal("1.002")).quantize(_PRICE_STEP)
            low = (min(open_, close) * Decimal("0.998")).quantize(_PRICE_STEP)
            bars.append(Bar(when, open_, high, low, close, rng.randint(1_000, 1_000_000)))
        return bars

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        inst = self._require(symbol)
        weekends = inst.type == "crypto"
        if interval in _HISTORY_CHUNK_MINUTES:
            if symbol not in _SESSIONS:
                raise DataUnavailable(f"The offline provider has no intraday history for {symbol}.")
            minutes = _HISTORY_CHUNK_MINUTES[interval]
            bars: list[Bar] = []
            for day in _days(start, end):
                bars.extend(_group(self._minute_bars(symbol, day), minutes))
            return bars
        if interval not in _INTERVAL_STEP_DAYS:
            raise DataUnavailable(f"The offline provider has no {interval} history.")
        daily = [self._daily_bar(symbol, day) for day in _days(start, end) if weekends or day.weekday() < 5]
        if interval == "1d":
            return daily

        # Weekly bars are labelled with their Monday, monthly with the 1st, as Yahoo does.
        def label(bar: Bar) -> str:
            day = date.fromisoformat(str(bar.time))
            first = day - timedelta(days=day.weekday()) if interval == "1wk" else day.replace(day=1)
            return first.isoformat()

        grouped: dict[str, list[Bar]] = {}
        for bar in daily:
            grouped.setdefault(label(bar), []).append(bar)
        return [_merge(members, key) for key, members in grouped.items()]

    def _day_close(self, symbol: str, day: date) -> Decimal:
        # A slow wave plus a little noise per day, a pure function of (symbol, day).
        phase = zlib.crc32(symbol.encode()) % 100 / 10
        wave = 0.06 * math.sin(day.toordinal() / 45 + phase)
        noise = random.Random(zlib.crc32(f"{symbol}:{day}".encode())).uniform(-0.01, 0.01)
        return (self._base[symbol] * (1 + Decimal(str(round(wave + noise, 6))))).quantize(_PRICE_STEP)

    def _daily_bar(self, symbol: str, day: date) -> Bar:
        close = self._day_close(symbol, day)
        rng = random.Random(zlib.crc32(f"{symbol}:{day}:d".encode()))
        open_ = (close * (1 + Decimal(str(round(rng.uniform(-0.006, 0.006), 5))))).quantize(_PRICE_STEP)
        high = (max(open_, close) * Decimal("1.003")).quantize(_PRICE_STEP)
        low = (min(open_, close) * Decimal("0.997")).quantize(_PRICE_STEP)
        return Bar(day.isoformat(), open_, high, low, close, rng.randint(1_000, 1_000_000))

    def _minute_bars(self, symbol: str, day: date) -> list[Bar]:
        """The 1-minute bars of one session, in true UTC. Empty on a day the market is shut."""
        zone, opens, length, weekdays_only = _SESSIONS[symbol]
        if weekdays_only and day.weekday() >= 5:
            return []
        start = datetime.combine(day, opens, tzinfo=ZoneInfo(zone)).astimezone(UTC)
        day_bar = self._daily_bar(symbol, day)
        rng = random.Random(zlib.crc32(f"{symbol}:{day}:m".encode()))
        bars: list[Bar] = []
        previous = day_bar.open
        for k in range(length):
            line = day_bar.open + (day_bar.close - day_bar.open) * (k + 1) / length
            noise = Decimal(str(round(rng.uniform(-0.0005, 0.0005), 6)))
            close = day_bar.close if k == length - 1 else (line * (1 + noise)).quantize(_PRICE_STEP)
            high = (max(previous, close) * Decimal("1.0003")).quantize(_PRICE_STEP)
            low = (min(previous, close) * Decimal("0.9997")).quantize(_PRICE_STEP)
            when = int((start + timedelta(minutes=k)).timestamp())
            bars.append(Bar(when, previous, high, low, close, rng.randint(100, 10_000)))
            previous = close
        return bars

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        inst = self._require(symbol)
        sector, industry, fields = _FUNDAMENTALS.get(symbol, (None, None, {}))
        with self._lock:
            price = self._price[symbol]
        return Fundamentals(
            symbol=symbol,
            sector=sector,
            industry=industry,
            currency=inst.currency,
            price=price if fields else None,
            **fields,
        )

    def _require(self, symbol: str) -> Instrument:
        inst = self._instruments.get(symbol)
        if inst is None:
            raise SymbolNotFound(symbol)
        return inst


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _merge(bars: list[Bar], when: str | int) -> Bar:
    return Bar(
        when,
        bars[0].open,
        max(b.high for b in bars),
        min(b.low for b in bars),
        bars[-1].close,
        sum(b.volume for b in bars),
    )


def _group(minute_bars: list[Bar], minutes: int) -> list[Bar]:
    # Buckets count from the session open, so a 375-minute NSE day gives 6 full 1h bars and a
    # short last one rather than bars straddling the open.
    return [
        _merge(minute_bars[i : i + minutes], minute_bars[i].time) for i in range(0, len(minute_bars), minutes)
    ]
