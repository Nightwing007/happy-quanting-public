import threading
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from cachetools import TTLCache

from .base import Bar, Fundamentals, Instrument, MarketDataProvider, Quote


class CachedProvider:
    """TTL cache around any provider. Yahoo rate-limits hard, so repeat calls must not reach it."""

    def __init__(
        self,
        inner: MarketDataProvider,
        quote_ttl: float,
        bars_ttl: float,
        fundamentals_ttl: float = 900,
    ):
        self._inner = inner
        self.name = getattr(inner, "name", "unknown")
        self._quotes: TTLCache = TTLCache(maxsize=2048, ttl=quote_ttl)
        self._bars: TTLCache = TTLCache(maxsize=512, ttl=bars_ttl)
        self._fundamentals: TTLCache = TTLCache(maxsize=512, ttl=fundamentals_ttl)
        self._searches: TTLCache = TTLCache(maxsize=256, ttl=bars_ttl)
        self._lock = threading.Lock()

    # The lock guards only the cache dicts. The upstream fetch happens outside it, so one slow
    # Yahoo call never blocks other symbols (worst case two threads fetch the same key once).
    def _cached(self, cache: TTLCache, key, fetch: Callable):
        with self._lock:
            if key in cache:
                return cache[key]
        value = fetch()
        with self._lock:
            cache[key] = value
        return value

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        key = (query.strip().lower(), limit)
        return self._cached(self._searches, key, lambda: self._inner.search(query, limit))

    def get_quote(self, symbol: str) -> Quote:
        return self._cached(self._quotes, symbol, lambda: self._inner.get_quote(symbol))

    def get_bars(self, symbol: str, interval: str, range_: str) -> list[Bar]:
        key = (symbol, interval, range_)
        return self._cached(self._bars, key, lambda: self._inner.get_bars(symbol, interval, range_))

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        # Not cached here: history.py keeps its own durable cache and decides what to fetch.
        return self._inner.get_history(symbol, interval, start, end)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        return self._cached(self._fundamentals, symbol, lambda: self._inner.get_fundamentals(symbol))

    def set_price(self, symbol: str, price: Decimal) -> None:
        # Only the fake has this; tests move the market through the cache with it.
        self._inner.set_price(symbol, price)  # type: ignore[attr-defined]
        with self._lock:
            self._quotes.pop(symbol, None)
