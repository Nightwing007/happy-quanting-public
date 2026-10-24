from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.config import get_settings

from .base import MarketDataError, MarketDataProvider, Quote
from .cache import CachedProvider


@lru_cache
def get_provider() -> MarketDataProvider:
    settings = get_settings()
    if settings.market_data_provider == "fake":
        from .fake import FakeProvider

        inner: MarketDataProvider = FakeProvider()
    else:
        # Imported lazily so the fake path never loads yfinance.
        from .yahoo import YahooProvider

        inner = YahooProvider()
    return CachedProvider(
        inner,
        settings.quote_cache_ttl_seconds,
        settings.bars_cache_ttl_seconds,
        settings.fundamentals_cache_ttl_seconds,
    )


def get_quotes(provider: MarketDataProvider, symbols: list[str]) -> dict[str, Quote]:
    """Fetch quotes in parallel. Symbols that raise MarketDataError are omitted from the result."""
    unique = list(dict.fromkeys(symbols))
    if not unique:
        return {}

    def fetch(symbol: str) -> Quote | None:
        try:
            return provider.get_quote(symbol)
        except MarketDataError:
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(unique))) as pool:
        results = list(pool.map(fetch, unique))
    return {s: q for s, q in zip(unique, results, strict=True) if q is not None}
