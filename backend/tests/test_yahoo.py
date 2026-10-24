"""Yahoo provider behaviour against mocked yfinance objects (no network)."""

import pandas as pd
import pytest

from app.market_data import yahoo
from app.market_data.base import DataUnavailable, SymbolNotFound
from app.market_data.yahoo import YahooProvider, _bars_from_frame

LAST_TRADE = 1792770900


def _frame(times, rows):
    index = pd.DatetimeIndex([pd.Timestamp(t, unit="s", tz="UTC") for t in times])
    return pd.DataFrame(rows, index=index, columns=["Open", "High", "Low", "Close", "Volume"])


class FakeTicker:
    def __init__(self, fast=None, history=None, fast_error=None, info=None):
        self._fast = fast if fast is not None else {
            "lastPrice": 190.5, "previousClose": 189.0, "currency": "USD", "exchange": "NMS"
        }
        self._history = history
        self._fast_error = fast_error
        self._info = info or {"longName": "Apple", "quoteType": "EQUITY"}
        self.history_calls = []

    @property
    def fast_info(self):
        if self._fast_error:
            raise self._fast_error
        return self._fast

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return self._history if self._history is not None else _frame([], [])

    def get_info(self):
        return self._info


class FakeSearch:
    """Stands in for yf.Search: `quotes` is whatever the test wants Yahoo to know about."""

    quotes: list[dict] = []

    def __init__(self, query, **kwargs):
        pass


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(yahoo, "_RETRY_DELAY", 0)
    FakeSearch.quotes = []  # by default Yahoo's search knows nothing
    monkeypatch.setattr(yahoo.yf, "Search", FakeSearch)


def _use(monkeypatch, *tickers):
    queue = list(tickers)
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda symbol: queue.pop(0) if len(queue) > 1 else queue[0])


def test_quote_as_of_is_last_bar_time_not_fetch_time(monkeypatch):
    ticker = FakeTicker(history=_frame([LAST_TRADE - 60, LAST_TRADE], [[1, 2, 1, 1.5, 10]] * 2))
    _use(monkeypatch, ticker)
    quote = YahooProvider().get_quote("AAPL")
    assert quote.as_of == LAST_TRADE
    assert ticker.history_calls[0]["prepost"] is False


def test_quote_as_of_falls_back_to_daily_bar(monkeypatch):
    class T(FakeTicker):
        def history(self, **kwargs):
            if kwargs["interval"] == "1m":
                return _frame([], [])
            return _frame([LAST_TRADE], [[1, 2, 1, 1.5, 10]])

    _use(monkeypatch, T())
    assert YahooProvider().get_quote("AAPL").as_of == LAST_TRADE


def test_quote_without_any_bar_is_unavailable(monkeypatch):
    _use(monkeypatch, FakeTicker(history=_frame([], [])))
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("AAPL")


@pytest.mark.parametrize(
    "error",
    [
        KeyError("currentTradingPeriod"),
        Exception("$ZZZZ: possibly delisted; no price data found"),
        Exception("HTTP Error 404: Quote not found for symbol: ZZZZ"),
        Exception("$ZZZZ: No data found, symbol may be delisted"),
    ],
)
def test_unknown_symbol_is_not_found(monkeypatch, error):
    _use(monkeypatch, FakeTicker(fast_error=error))
    with pytest.raises(SymbolNotFound):
        YahooProvider().get_quote("ZZZZNOPE")


def test_suspicious_error_for_a_real_symbol_is_unavailable_not_not_found(monkeypatch):
    # A bare KeyError is what Yahoo throws on a hiccup too; recent bars prove the symbol exists.
    bars = _frame([LAST_TRADE], [[1, 2, 1, 1.5, 10]])
    _use(monkeypatch, FakeTicker(fast_error=KeyError("currentTradingPeriod"), history=bars))
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("BTC-USD")


def test_suspicious_error_is_unavailable_when_search_still_knows_the_symbol(monkeypatch):
    FakeSearch.quotes = [{"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY"}]
    _use(monkeypatch, FakeTicker(fast_error=KeyError("currentTradingPeriod")))
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("btc-usd")


def test_unconfirmable_absence_is_unavailable(monkeypatch):
    # The confirming call itself fails: nothing proves the symbol is missing.
    class Broken(FakeTicker):
        def history(self, **kwargs):
            raise ConnectionError("down")

    _use(monkeypatch, Broken(fast_error=KeyError("currentTradingPeriod")))
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("AAPL")


def test_empty_history_for_a_known_symbol_is_unavailable(monkeypatch):
    FakeSearch.quotes = [{"symbol": "AAPL"}]
    _use(monkeypatch, FakeTicker())
    with pytest.raises(DataUnavailable):
        YahooProvider().get_bars("AAPL", "1h", "1mo")


def test_missing_price_is_not_found(monkeypatch):
    fast = {"lastPrice": None, "previousClose": None, "currency": "USD", "exchange": "NMS"}
    _use(monkeypatch, FakeTicker(fast=fast))
    with pytest.raises(SymbolNotFound):
        YahooProvider().get_quote("ZZZZNOPE")


def test_rate_limit_stays_unavailable_and_is_not_retried(monkeypatch):
    calls = []

    def ticker(symbol):
        calls.append(symbol)
        return FakeTicker(fast_error=Exception("Too Many Requests. Rate limited."))

    monkeypatch.setattr(yahoo.yf, "Ticker", ticker)
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("AAPL")
    assert len(calls) == 1


def test_connection_reset_is_retried_once(monkeypatch):
    bad = FakeTicker(fast_error=ConnectionError("[WinError 10054] connection reset by peer"))
    good = FakeTicker(history=_frame([LAST_TRADE], [[1, 2, 1, 1.5, 10]]))
    _use(monkeypatch, bad, good)
    assert YahooProvider().get_quote("AAPL").as_of == LAST_TRADE


def test_connection_reset_twice_gives_up(monkeypatch):
    calls = []

    def ticker(symbol):
        calls.append(symbol)
        return FakeTicker(fast_error=TimeoutError("timed out"))

    monkeypatch.setattr(yahoo.yf, "Ticker", ticker)
    with pytest.raises(DataUnavailable):
        YahooProvider().get_quote("AAPL")
    assert len(calls) == 2


def test_daily_bar_range_is_widened_to_cover_open_and_close():
    # high below the close and low above the open: Yahoo glitches
    frame = _frame([1700000000], [[10, 9, 11, 12, 100]])
    (bar,) = _bars_from_frame(frame, "1d", "USD", shift_to_local=False)
    assert bar.high == 12 and bar.low == 10


def test_flat_zero_volume_intraday_bar_is_kept():
    frame = _frame([1700000000], [[10, 10, 10, 10, 0]])
    (bar,) = _bars_from_frame(frame, "5m", "USD", shift_to_local=False)
    assert bar.volume == 0 and bar.open == bar.close == 10
