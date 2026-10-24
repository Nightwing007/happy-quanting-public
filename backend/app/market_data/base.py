from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

# Indexes and currencies can be charted, not traded.
TRADABLE_TYPES = frozenset({"equity", "etf", "crypto"})

# What Yahoo will serve for each bar interval. Intraday history is capped by Yahoo:
# 1m reaches back about 7 days, sub-hour intervals about 60 days, 1h about 730 days.
ALLOWED_RANGES: dict[str, tuple[str, ...]] = {
    "1m": ("1d", "5d"),
    "5m": ("1d", "5d", "1mo"),
    "15m": ("1d", "5d", "1mo"),
    "30m": ("1d", "5d", "1mo"),
    "1h": ("1d", "5d", "1mo", "3mo", "6mo", "1y"),
    "1d": ("1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"),
    "1wk": ("6mo", "1y", "2y", "5y", "10y", "ytd", "max"),
    "1mo": ("1y", "2y", "5y", "10y", "ytd", "max"),
}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    exchange: str
    type: str  # equity | etf | crypto | index | currency
    currency: str


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    exchange: str
    type: str
    currency: str
    price: Decimal
    previous_close: Decimal | None
    as_of: int  # unix seconds


@dataclass(frozen=True)
class Bar:
    # "YYYY-MM-DD" for daily and longer intervals; exchange-local unix seconds for intraday.
    time: str | int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Fundamentals:
    """Company (or coin) figures, already normalized. None means the source gave no usable figure.

    Units are fixed here so nothing downstream has to know Yahoo's quirks: ratios are plain
    multiples, ROE and yield are percentages (18.5 means 18.5%), D/E is a ratio (0.45 means
    debt is 45% of equity). Money fields are in `currency`.
    """

    symbol: str
    sector: str | None
    industry: str | None
    currency: str | None
    trailing_pe: Decimal | None = None
    price_to_book: Decimal | None = None
    return_on_equity: Decimal | None = None  # percent
    debt_to_equity: Decimal | None = None  # ratio
    dividend_yield: Decimal | None = None  # percent
    market_cap: Decimal | None = None
    volume_24h: Decimal | None = None
    circulating_supply: Decimal | None = None
    fifty_two_week_low: Decimal | None = None
    fifty_two_week_high: Decimal | None = None
    price: Decimal | None = None


class MarketDataError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SymbolNotFound(MarketDataError):
    def __init__(self, symbol: str):
        super().__init__(
            f"No market data found for '{symbol}'. Check the symbol — Indian stocks need .NS or .BO."
        )
        self.symbol = symbol


class DataUnavailable(MarketDataError):
    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "Yahoo Finance isn't responding right now (it rate-limits heavy use). Try again in a minute."
        )


class MarketDataProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 10) -> list[Instrument]: ...

    def get_quote(self, symbol: str) -> Quote: ...

    def get_bars(self, symbol: str, interval: str, range_: str) -> list[Bar]: ...

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        """Bars for the calendar days start..end, both inclusive; [] when the market never traded.

        Unlike `get_bars`, an intraday `Bar.time` here is true UTC unix seconds (the cache and the
        replay compare times across markets, so they must not be shifted into exchange-local
        clock time). Daily and longer bars keep "YYYY-MM-DD".
        """
        ...
