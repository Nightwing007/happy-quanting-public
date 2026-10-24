"""Yahoo Finance provider. The only module in the codebase allowed to import yfinance."""

import math
import time
import warnings
from datetime import date, timedelta
from decimal import Decimal

import yfinance as yf

from .base import (
    Bar,
    DataUnavailable,
    Fundamentals,
    Instrument,
    MarketDataError,
    Quote,
    SymbolNotFound,
)

# yfinance itself raises pandas deprecation warnings under pandas 3.x; they're not ours to fix.
warnings.filterwarnings("ignore", module="yfinance")

# Yahoo quote types -> ours. Anything not listed (options, futures, mutual funds) is skipped.
_TYPE_MAP = {
    "EQUITY": "equity",
    "ETF": "etf",
    "CRYPTOCURRENCY": "crypto",
    "INDEX": "index",
    "CURRENCY": "currency",
}

# Minor-unit currencies: Yahoo quotes London stocks in pence, etc.
_MINOR_UNITS = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}

_DAILY_PLUS = {"1d", "1wk", "1mo"}

# One retry after this pause for a dropped connection or timeout (WinError 10054 and friends).
_RETRY_DELAY = 0.5


def normalize_price(value: Decimal, currency: str) -> tuple[Decimal, str]:
    # Without this every London price is 100x too big (pence read as pounds).
    major = _MINOR_UNITS.get(currency)
    if major is None:
        return value, currency
    return value / 100, major


def to_decimal(value: float) -> Decimal:
    # Never Decimal(float): that exposes binary noise (0.1000000000000000055...).
    # Yahoo's numbers are float32-derived (118.2 arrives as 118.19999695), so rounding to many
    # places keeps the dust. Round by magnitude instead: 4 decimals from 1 upward, 6 significant
    # digits below 1 (so tiny FX and crypto prices stay meaningful). Do this in the currency Yahoo
    # quoted, before normalize_price divides pence down to pounds.
    number = float(value)
    rounded = round(number, 4) if abs(number) >= 1 else float(f"{number:.6g}")
    text = f"{Decimal(repr(rounded)):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text)


def _clean(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) or math.isinf(number) else number


def _number(value) -> Decimal | None:
    """A finite Yahoo number as a clean Decimal, or None for missing, NaN, infinite or non-numeric."""
    try:
        number = _clean(value)
    except TypeError, ValueError:
        return None
    return None if number is None else to_decimal(number)


def _money(value, currency: str) -> Decimal | None:
    number = _number(value)
    return None if number is None else normalize_price(number, currency)[0]


def fundamentals_from_info(symbol: str, info: dict) -> Fundamentals:
    """Turn Yahoo's raw `Ticker.info` into our units. Pure, so it is tested without the network."""
    quoted_currency = info.get("currency") or ""
    currency = normalize_price(Decimal(0), quoted_currency)[1] or None
    crypto = str(info.get("quoteType", "")).upper() == "CRYPTOCURRENCY"

    raw_price = _number(info.get("currentPrice"))
    if raw_price is None:
        raw_price = _number(info.get("regularMarketPrice"))

    # Yahoo's returnOnEquity is a fraction (0.185 = 18.5%); we hold percentages.
    roe = _number(info.get("returnOnEquity"))
    # Yahoo's debtToEquity is a percentage (45.0 = debt is 45% of equity); we hold the ratio, 0.45.
    de = _number(info.get("debtToEquity"))

    # Deliberately not `dividendYield`: yfinance changed it from a fraction to a percent between
    # releases, so the same field would be off by 100x depending on the installed version.
    # dividendRate (cash per share per year) over price means the same thing in every release.
    # Yahoo quotes London prices in pence but gives dividendRate in pounds (checked live on VOD.L:
    # price 118.2, dividendRate 0.04, true yield about 3.3%), so divide by the price in major
    # units. Dividing pounds by pence would understate the yield 100x.
    rate = _number(info.get("dividendRate"))
    price = None if raw_price is None else normalize_price(raw_price, quoted_currency)[0]
    dividend_yield = None
    if rate is not None and rate > 0 and price is not None and price > 0:
        dividend_yield = rate / price * 100

    volume = _number(info.get("volume24Hr"))
    if volume is None and crypto:
        volume = _number(info.get("volume"))  # some crypto records only carry the plain field

    return Fundamentals(
        symbol=symbol,
        sector=info.get("sector") or None,
        industry=info.get("industry") or None,
        currency=currency,
        trailing_pe=_number(info.get("trailingPE")),
        price_to_book=_number(info.get("priceToBook")),
        return_on_equity=None if roe is None else roe * 100,
        debt_to_equity=None if de is None else de / 100,
        dividend_yield=dividend_yield,
        market_cap=_number(info.get("marketCap")),
        volume_24h=volume,
        circulating_supply=_number(info.get("circulatingSupply")),
        # Prices are in the quote currency's minor unit for London etc., like everywhere else.
        fifty_two_week_low=_money(info.get("fiftyTwoWeekLow"), quoted_currency),
        fifty_two_week_high=_money(info.get("fiftyTwoWeekHigh"), quoted_currency),
        price=price,
    )


def _looks_missing(exc: Exception) -> bool:
    if isinstance(exc, MarketDataError):
        return False
    # For an unknown symbol fast_info raises a bare KeyError('currentTradingPeriod'): the chart
    # metadata Yahoo returns has no trading period, and the "No data found" text is only logged.
    if isinstance(exc, LookupError):
        return True
    text = str(exc).lower()
    return any(
        phrase in text
        for phrase in ("no data found", "delisted", "not found", "404", "no timezone", "no price data")
    )


def _is_transient(exc: Exception) -> bool:
    """A dropped connection or timeout: worth one retry. Never a rate limit or a missing symbol."""
    text = str(exc).lower()
    if "too many requests" in text or "rate limit" in text or "429" in text:
        return False
    if _looks_missing(exc):
        return False
    if isinstance(exc, ConnectionError | TimeoutError):
        return True
    return any(
        phrase in text
        for phrase in ("10054", "connection reset", "connection aborted", "timed out", "timeout")
    )


def _with_retry(fn):
    try:
        return fn()
    except Exception as exc:
        if not _is_transient(exc):
            raise
    time.sleep(_RETRY_DELAY)
    return fn()


def _bars_from_frame(frame, interval: str, currency: str, *, shift_to_local: bool) -> list[Bar]:
    daily = interval in _DAILY_PLUS
    bars: list[Bar] = []
    for index, row in frame.iterrows():
        values = [_clean(row[col]) for col in ("Open", "High", "Low", "Close")]
        if any(v is None for v in values):
            continue
        if daily:
            bar_time: str | int = index.strftime("%Y-%m-%d")
        elif shift_to_local:
            # The chart library treats times as UTC, so shifting by the exchange's UTC
            # offset makes the time axis show exchange-local clock time.
            bar_time = int(index.timestamp()) + int(index.utcoffset().total_seconds())
        else:
            bar_time = int(index.timestamp())  # history keeps true UTC; see get_history in base.py
        o, h, low, c = (normalize_price(to_decimal(v), currency)[0] for v in values)
        if daily:
            # Yahoo's daily/weekly data sometimes has a high below the open/close or a low above
            # it; widen the range so the candle is valid (intraday bars are left as they come).
            h = max(h, o, c)
            low = min(low, o, c)
        volume = _clean(row.get("Volume")) or 0
        bars.append(Bar(time=bar_time, open=o, high=h, low=low, close=c, volume=int(volume)))
    return bars


def _last_trade_time(ticker) -> int | None:
    """Unix time of the newest regular-session bar, not the time we fetched it.

    `hours.can_fill` compares this with the session open to refuse yesterday's close right after
    the open, so a fetch-time stamp would make a stale quote look fresh.
    """
    for interval in ("1m", "1d"):  # 1m gives the real last-trade minute; 1d is the coarse fallback
        frame = ticker.history(period="5d", interval=interval, auto_adjust=False, prepost=False)
        if frame is not None and not frame.empty:
            return int(frame.index[-1].timestamp())
    return None


class YahooProvider:
    name = "yahoo"

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        try:
            quotes = yf.Search(query, max_results=limit, news_count=0).quotes
        except Exception as exc:
            raise DataUnavailable() from exc
        found: list[Instrument] = []
        for item in quotes:
            kind = _TYPE_MAP.get(str(item.get("quoteType", "")).upper())
            symbol = item.get("symbol")
            if kind is None or not symbol:
                continue
            found.append(
                Instrument(
                    symbol=symbol,
                    name=item.get("longname") or item.get("shortname") or symbol,
                    exchange=item.get("exchDisp") or item.get("exchange") or "",
                    type=kind,
                    currency=item.get("currency") or "",
                )
            )
        return found[:limit]

    def get_quote(self, symbol: str) -> Quote:
        def fetch():
            ticker = yf.Ticker(symbol)
            fast = ticker.fast_info
            price = _clean(fast["lastPrice"])
            previous = _clean(fast["previousClose"])
            currency = fast["currency"] or ""
            exchange = fast["exchange"] or ""
            as_of = _last_trade_time(ticker) if price is not None else 0
            return ticker, price, previous, currency, exchange, as_of

        try:
            ticker, price, previous, currency, exchange, as_of = _with_retry(fetch)
        except Exception as exc:
            if _looks_missing(exc):
                raise SymbolNotFound(symbol) from exc
            raise DataUnavailable() from exc
        if price is None:
            raise SymbolNotFound(symbol)
        if as_of is None:
            raise DataUnavailable()

        name, kind = symbol, "equity"
        try:
            info = ticker.get_info()
            name = info.get("longName") or info.get("shortName") or symbol
            kind = _TYPE_MAP.get(str(info.get("quoteType", "")).upper(), kind)
        except Exception:
            pass  # name and type are cosmetic; the price is what matters

        price_dec, ccy = normalize_price(to_decimal(price), currency)
        prev_dec = None
        if previous is not None:
            prev_dec, _ = normalize_price(to_decimal(previous), currency)
        return Quote(
            symbol=symbol,
            name=name,
            exchange=exchange,
            type=kind,
            currency=ccy,
            price=price_dec,
            previous_close=prev_dec,
            as_of=as_of,
        )

    def get_bars(self, symbol: str, interval: str, range_: str) -> list[Bar]:
        try:
            def fetch():
                ticker = yf.Ticker(symbol)
                frame = ticker.history(period=range_, interval=interval, auto_adjust=False)
                return frame, ticker.fast_info["currency"] or ""

            frame, currency = _with_retry(fetch)
        except Exception as exc:
            if _looks_missing(exc):
                raise SymbolNotFound(symbol) from exc
            raise DataUnavailable() from exc
        if frame is None or frame.empty:
            raise SymbolNotFound(symbol)

        bars = _bars_from_frame(frame, interval, currency, shift_to_local=True)
        if not bars:
            raise SymbolNotFound(symbol)
        return bars

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        try:
            def fetch():
                ticker = yf.Ticker(symbol)
                # Yahoo's `end` is exclusive; ours is the last day wanted.
                frame = ticker.history(
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    interval=interval,
                    auto_adjust=False,
                )
                return frame, ticker.fast_info["currency"] or ""

            frame, currency = _with_retry(fetch)
        except Exception as exc:
            if _looks_missing(exc):
                raise SymbolNotFound(symbol) from exc
            raise DataUnavailable() from exc
        # An empty frame is a weekend or a holiday, not an error: the caller records the span.
        if frame is None or frame.empty:
            return []
        return _bars_from_frame(frame, interval, currency, shift_to_local=False)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        try:
            info = _with_retry(lambda: yf.Ticker(symbol).get_info())
        except Exception as exc:
            if _looks_missing(exc):
                raise SymbolNotFound(symbol) from exc
            raise DataUnavailable() from exc
        return fundamentals_from_info(symbol, info or {})
