from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data import get_provider, get_quotes
from app.market_data.base import ALLOWED_RANGES, TRADABLE_TYPES, MarketDataError, SymbolNotFound
from app.market_data.cache import CachedProvider
from app.market_data.fake import FakeProvider
from app.market_data.fx import get_fx_rate
from app.market_data.yahoo import normalize_price, to_decimal


def test_normalize_price_minor_units():
    # Pence -> pounds: 12345p = 123.45 GBP. Rand cents and agorot work the same way.
    assert normalize_price(Decimal("12345"), "GBp") == (Decimal("123.45"), "GBP")
    assert normalize_price(Decimal("12345"), "GBX") == (Decimal("123.45"), "GBP")
    assert normalize_price(Decimal("5000"), "ZAc") == (Decimal("50"), "ZAR")
    assert normalize_price(Decimal("250"), "ILA") == (Decimal("2.5"), "ILS")
    assert normalize_price(Decimal("230.5"), "USD") == (Decimal("230.5"), "USD")


def test_to_decimal_has_no_float_noise():
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(230.1234567891) == Decimal("230.1235")
    assert str(to_decimal(100.0)) == "100"


def test_to_decimal_strips_float32_dust_from_live_yahoo_values():
    # Values >= 1 round to 4 places; values < 1 keep 6 significant digits.
    assert to_decimal(346.23001099) == Decimal("346.23")  # 346.2300|1099 -> 346.2300 -> 346.23
    assert to_decimal(81392.3515625) == Decimal("81392.3516")  # 5th decimal is 5, rounds up
    assert to_decimal(0.0105299996) == Decimal("0.01053")  # 6 sig digits: 0.0105300 -> 0.01053


def test_pence_are_rounded_before_conversion_to_pounds():
    # 118.19999695 GBp -> 118.2 (rounded in pence), then / 100 -> 1.182 GBP.
    assert normalize_price(to_decimal(118.19999695), "GBp") == (Decimal("1.182"), "GBP")


def test_fake_quote():
    quote = FakeProvider().get_quote("AAPL")
    assert quote.symbol == "AAPL"
    assert quote.currency == "USD"
    assert quote.price == Decimal("230")
    assert quote.previous_close is not None


def test_fake_unknown_symbol():
    with pytest.raises(SymbolNotFound) as info:
        FakeProvider().get_quote("NOPE")
    assert "NOPE" in info.value.message
    assert isinstance(info.value, MarketDataError)


def test_fake_search_matches_symbol_and_name_case_insensitively():
    provider = FakeProvider()
    assert [i.symbol for i in provider.search("aapl")] == ["AAPL"]
    assert "RELIANCE.NS" in [i.symbol for i in provider.search("reliance")]
    assert len(provider.search("reliance", limit=1)) == 1
    assert provider.search("zzzzz") == []


def test_fake_bars_daily_strings_intraday_ints():
    provider = FakeProvider()
    daily = provider.get_bars("AAPL", "1d", "1mo")
    assert all(isinstance(b.time, str) and len(b.time) == 10 for b in daily)
    intraday = provider.get_bars("AAPL", "5m", "1d")
    assert all(isinstance(b.time, int) for b in intraday)


def test_fake_bars_deterministic_and_end_at_current_price():
    provider = FakeProvider()
    first = provider.get_bars("MSFT", "1d", "3mo")
    assert first == provider.get_bars("MSFT", "1d", "3mo")
    assert first[-1].close == provider.get_quote("MSFT").price
    assert all(b.low <= b.open <= b.high and b.low <= b.close <= b.high for b in first)


def test_every_allowed_range_is_served_by_the_fake():
    provider = FakeProvider()
    for interval, ranges in ALLOWED_RANGES.items():
        for range_ in ranges:
            assert provider.get_bars("AAPL", interval, range_)


def test_set_price_through_cache_changes_quote():
    provider = CachedProvider(FakeProvider(), quote_ttl=30, bars_ttl=300)
    assert provider.get_quote("AAPL").price == Decimal("230")
    provider.set_price("AAPL", Decimal("250.5"))
    assert provider.get_quote("AAPL").price == Decimal("250.5")
    assert provider.get_bars("AAPL", "1d", "1mo")[-1].close == Decimal("250.5")


def test_cache_serves_repeat_quotes_from_memory():
    inner = FakeProvider()
    provider = CachedProvider(inner, quote_ttl=30, bars_ttl=300)
    first = provider.get_quote("AAPL")
    inner.set_price("AAPL", Decimal("999"))  # bypasses the cache on purpose
    assert provider.get_quote("AAPL") is first


def test_fx_rates():
    provider = FakeProvider()
    assert get_fx_rate(provider, "USD", "USD") == Decimal(1)
    assert get_fx_rate(provider, "USD", "INR") == Decimal("83.5")
    assert get_fx_rate(provider, "HKD", "INR") > 0


def test_fx_pairs_for_every_fake_currency_exist():
    provider = FakeProvider()
    for pair in ("EURINR", "GBPINR", "EURUSD", "GBPUSD", "INRUSD", "HKDINR", "HKDUSD"):
        assert provider.get_quote(f"{pair}=X").type == "currency"


def test_tradable_types():
    assert TRADABLE_TYPES == {"equity", "etf", "crypto"}


def test_get_provider_is_the_offline_fake():
    provider = get_provider()
    assert isinstance(provider, CachedProvider)
    assert isinstance(provider._inner, FakeProvider)


def test_get_quotes_skips_unknown_symbols():
    quotes = get_quotes(FakeProvider(), ["AAPL", "NOPE", "MSFT", "AAPL"])
    assert set(quotes) == {"AAPL", "MSFT"}


def test_only_yahoo_module_imports_yfinance():
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if path.name != "yahoo.py"
        and any(
            line.strip().startswith(("import yfinance", "from yfinance"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert offenders == []
