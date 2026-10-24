from decimal import Decimal

from fastapi.testclient import TestClient

from app import metrics
from app.market_data.base import Fundamentals
from app.market_data.cache import CachedProvider
from app.market_data.fake import FakeProvider
from app.market_data.yahoo import fundamentals_from_info


def _equity(sector: str | None, **fields: str | None) -> Fundamentals:
    return Fundamentals(
        symbol="TEST",
        sector=sector,
        industry=None,
        currency="USD",
        **{k: None if v is None else Decimal(v) for k, v in fields.items()},
    )


def _by_key(result):
    return {m.key: m for m in result.metrics}


# --- sector-relative verdicts -------------------------------------------------------------


def test_pe_of_30_is_typical_for_technology_and_above_usual_for_financial_services():
    tech = metrics.build_metrics(_equity("Technology", trailing_pe="30"), "equity", "USD")
    bank = metrics.build_metrics(_equity("Financial Services", trailing_pe="30"), "equity", "USD")
    assert _by_key(tech)["pe"].assessment == "typical"
    assert _by_key(bank)["pe"].assessment == "above usual"


def test_assess_bounds_are_typical_and_outside_is_not():
    band = (Decimal("20"), Decimal("40"))
    assert metrics.assess(Decimal("19.9"), band) == "below usual"
    assert metrics.assess(Decimal("20"), band) == "typical"
    assert metrics.assess(Decimal("40"), band) == "typical"
    assert metrics.assess(Decimal("40.1"), band) == "above usual"


def test_every_metric_has_all_eleven_sectors_and_a_default():
    for metric in (metrics.PE, metrics.PB, metrics.ROE, metrics.DIVIDEND_YIELD):
        assert set(metric.ranges) == {*metrics.SECTORS, "default"}
    # Debt-to-equity has no financial-services band: the metric is omitted there.
    assert set(metrics.DE.ranges) == {*metrics.SECTORS, "default"} - {"Financial Services"}
    for metric in (metrics.PE, metrics.PB, metrics.ROE, metrics.DE, metrics.DIVIDEND_YIELD):
        assert all(low < high for low, high in metric.ranges.values())


def test_unknown_or_missing_sector_uses_the_default_band():
    result = metrics.build_metrics(_equity(None, trailing_pe="30"), "equity", "USD")
    pe = _by_key(result)["pe"]
    assert pe.range.label == "All sectors"
    assert (pe.range.low, pe.range.high) == metrics.PE.ranges["default"]
    odd = metrics.build_metrics(_equity("Space Mining", trailing_pe="30"), "equity", "USD")
    assert _by_key(odd)["pe"].range.label == "All sectors"


def test_assessment_comes_with_a_plain_meaning_in_both_directions():
    low = metrics.build_metrics(_equity("Technology", trailing_pe="5"), "equity", "USD")
    high = metrics.build_metrics(_equity("Technology", trailing_pe="90"), "equity", "USD")
    mid = metrics.build_metrics(_equity("Technology", trailing_pe="30"), "equity", "USD")
    meanings = {_by_key(r)["pe"].meaning for r in (low, high, mid)}
    assert len(meanings) == 3


# --- omission ------------------------------------------------------------------------------


def test_metric_with_no_figure_is_omitted_not_blank():
    result = metrics.build_metrics(
        _equity("Technology", trailing_pe="30", price_to_book="12", return_on_equity="50"),
        "equity",
        "USD",
    )
    assert [m.key for m in result.metrics] == ["pe", "pb", "roe"]
    assert result.omitted == []  # missing is not an explained omission


def test_pe_and_pb_at_or_below_zero_are_omitted_but_negative_roe_is_kept():
    result = metrics.build_metrics(
        _equity("Technology", trailing_pe="-5", price_to_book="0", return_on_equity="-12"),
        "equity",
        "USD",
    )
    assert [m.key for m in result.metrics] == ["roe"]
    assert result.metrics[0].assessment == "below usual"


def test_debt_to_equity_is_omitted_for_financial_services_with_the_reason():
    result = metrics.build_metrics(
        _equity("Financial Services", trailing_pe="15", debt_to_equity="0.9"), "equity", "USD"
    )
    assert "de" not in _by_key(result)
    assert [o.key for o in result.omitted] == ["de"]
    assert result.omitted[0].reason == (
        "Banks borrow as their raw material, so debt-to-equity says little; "
        "regulators look at capital adequacy instead."
    )


def test_debt_to_equity_is_shown_for_other_sectors():
    result = metrics.build_metrics(_equity("Energy", debt_to_equity="0.38"), "equity", "USD")
    assert _by_key(result)["de"].value == Decimal("0.38")
    assert result.omitted == []


# --- Yahoo normalization -------------------------------------------------------------------


def test_yahoo_units_are_normalized():
    info = {
        "currency": "USD",
        "sector": "Technology",
        "returnOnEquity": 0.185,  # fraction -> 18.5 percent
        "debtToEquity": 45.0,  # percentage -> 0.45 ratio
        "dividendYield": 0.0125,  # ignored: its meaning changed between yfinance releases
        "dividendRate": 2.0,
        "currentPrice": 80.0,  # 2.0 / 80 * 100 = 2.5 percent
        "trailingPE": 24.8,
        "priceToBook": 8.0,
    }
    f = fundamentals_from_info("XYZ", info)
    assert f.return_on_equity == Decimal("18.5")
    assert f.debt_to_equity == Decimal("0.45")
    assert f.dividend_yield == Decimal("2.5")
    assert f.trailing_pe == Decimal("24.8")
    assert f.price == Decimal("80")
    assert f.sector == "Technology"


def test_yahoo_dividend_yield_falls_back_to_regular_market_price():
    f = fundamentals_from_info("XYZ", {"currency": "USD", "dividendRate": 3.0, "regularMarketPrice": 120.0})
    assert f.dividend_yield == Decimal("2.5")  # 3 / 120 * 100


def test_yahoo_pence_are_converted_and_do_not_distort_the_yield():
    info = {
        "currency": "GBp",
        "currentPrice": 72.0,  # pence, so 0.72 GBP
        "dividendRate": 0.04,  # pounds, as Yahoo really sends it: 0.04 / 0.72 * 100 = 5.5556 percent
        "fiftyTwoWeekLow": 50.0,
        "fiftyTwoWeekHigh": 90.0,
    }
    f = fundamentals_from_info("VOD.L", info)
    assert f.currency == "GBP"
    assert f.price == Decimal("0.72")
    assert f.fifty_two_week_low == Decimal("0.5")
    assert f.fifty_two_week_high == Decimal("0.9")
    assert f.dividend_yield.quantize(Decimal("0.01")) == Decimal("5.56")


def test_yahoo_missing_nan_and_infinite_values_become_none():
    info = {
        "currency": "USD",
        "trailingPE": float("nan"),
        "priceToBook": float("inf"),
        "returnOnEquity": None,
        "debtToEquity": "n/a",
        "dividendRate": 0,
        "currentPrice": 100.0,
    }
    f = fundamentals_from_info("XYZ", info)
    assert f.trailing_pe is None
    assert f.price_to_book is None
    assert f.return_on_equity is None
    assert f.debt_to_equity is None
    assert f.dividend_yield is None  # a zero dividend is "pays none", not a 0% figure


def test_yahoo_crypto_fields_and_volume_fallback():
    info = {
        "currency": "USD",
        "quoteType": "CRYPTOCURRENCY",
        "marketCap": 1.2e12,
        "volume": 3.5e10,  # no volume24Hr on this record
        "circulatingSupply": 19_800_000,
        "fiftyTwoWeekLow": 40000.0,
        "fiftyTwoWeekHigh": 75000.0,
        "regularMarketPrice": 60000.0,
    }
    f = fundamentals_from_info("BTC-USD", info)
    assert f.market_cap == Decimal("1200000000000")
    assert f.volume_24h == Decimal("35000000000")
    assert f.circulating_supply == Decimal("19800000")
    assert f.price == Decimal("60000")


def test_yahoo_volume_is_not_a_24_hour_figure_for_shares():
    f = fundamentals_from_info("AAPL", {"currency": "USD", "quoteType": "EQUITY", "volume": 5_000_000})
    assert f.volume_24h is None


# --- crypto --------------------------------------------------------------------------------


def test_crypto_gets_its_four_with_the_52_week_position():
    # (60000 - 40000) / (75000 - 40000) = 20000 / 35000 = 0.5714... -> 57.14 percent.
    f = FakeProvider().get_fundamentals("BTC-USD")
    result = metrics.build_metrics(f, "crypto", "USD")
    by_key = _by_key(result)
    assert list(by_key) == ["market_cap", "volume_24h", "circulating_supply", "range_position"]
    assert by_key["range_position"].value == Decimal("57.14")
    assert (by_key["range_position"].range.low, by_key["range_position"].range.high) == (
        Decimal("40000"),
        Decimal("75000"),
    )
    assert by_key["market_cap"].value == Decimal("1200000000000")
    assert all(m.assessment is None for m in result.metrics)


def test_crypto_position_is_clamped_when_price_leaves_the_range():
    f = Fundamentals(
        symbol="X",
        sector=None,
        industry=None,
        currency="USD",
        price=Decimal("80000"),
        fifty_two_week_low=Decimal("40000"),
        fifty_two_week_high=Decimal("75000"),
    )
    pos = _by_key(metrics.build_metrics(f, "crypto", "USD"))["range_position"]
    assert pos.value == Decimal("100")


def test_crypto_with_no_figures_has_no_metrics():
    f = Fundamentals(symbol="X", sector=None, industry=None, currency="USD")
    assert metrics.build_metrics(f, "crypto", "USD").metrics == []


# --- endpoint ------------------------------------------------------------------------------


def test_endpoint_shape_and_trimmed_strings(client: TestClient):
    body = client.get("/api/market/metrics", params={"symbol": "aapl"}).json()
    assert body["symbol"] == "AAPL"
    assert body["kind"] == "equity"
    assert body["sector"] == "Technology"
    assert body["currency"] == "USD"
    assert body["note"].startswith("Sector ranges are rules of thumb from NYU Stern (Damodaran)")
    assert body["note"].endswith("Yahoo Finance publishes no sector benchmarks.")
    pe = body["metrics"][0]
    assert set(pe) == {
        "key",
        "label",
        "value",
        "unit",
        "display_hint",
        "assessment",
        "range",
        "explanation",
        "better",
        "meaning",
        "if_below",
        "if_above",
    }
    assert pe["key"] == "pe" and pe["value"] == "24.8"  # not "24.80"
    assert pe["unit"] == "x" and pe["assessment"] == "typical"
    assert pe["range"] == {"low": "20", "high": "40", "label": "Technology"}
    values = {m["key"]: m["value"] for m in body["metrics"]}
    assert values["pb"] == "8.45" and values["roe"] == "45.2" and values["de"] == "1.5"


def test_endpoint_drops_the_metric_with_no_figure(client: TestClient):
    body = client.get("/api/market/metrics", params={"symbol": "TCS.NS"}).json()
    keys = [m["key"] for m in body["metrics"]]
    assert keys == ["pe", "pb", "roe", "dividend_yield"]
    assert next(m for m in body["metrics"] if m["key"] == "pe")["assessment"] == "typical"  # P/E 30
    assert body["omitted"] == []


def test_endpoint_bank_omits_debt_to_equity_with_reason(client: TestClient):
    body = client.get("/api/market/metrics", params={"symbol": "HDFCBANK.NS"}).json()
    assert body["sector"] == "Financial Services"
    assert "de" not in [m["key"] for m in body["metrics"]]
    assert body["omitted"][0]["key"] == "de"
    assert "capital adequacy" in body["omitted"][0]["reason"]


def test_endpoint_crypto(client: TestClient):
    body = client.get("/api/market/metrics", params={"symbol": "BTC-USD"}).json()
    assert body["kind"] == "crypto"
    assert [m["key"] for m in body["metrics"]] == [
        "market_cap",
        "volume_24h",
        "circulating_supply",
        "range_position",
    ]
    assert body["metrics"][3]["value"] == "57.14"
    assert body["metrics"][0]["assessment"] is None


def test_endpoint_index_is_200_with_an_empty_list_and_a_note(client: TestClient):
    response = client.get("/api/market/metrics", params={"symbol": "^GSPC"})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "other" and body["metrics"] == [] and body["omitted"] == []
    assert "indexes" in body["note"]


def test_endpoint_equity_without_fundamentals_is_empty_not_an_error(client: TestClient):
    body = client.get("/api/market/metrics", params={"symbol": "SAP.DE"}).json()
    assert body["kind"] == "equity" and body["metrics"] == []


def test_endpoint_unknown_symbol_is_404(client: TestClient):
    assert client.get("/api/market/metrics", params={"symbol": "NOPE"}).status_code == 404


# --- cache ---------------------------------------------------------------------------------


class _Counting(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        self.calls += 1
        return super().get_fundamentals(symbol)


def test_fundamentals_are_cached_after_the_first_call():
    inner = _Counting()
    cached = CachedProvider(inner, quote_ttl=30, bars_ttl=300, fundamentals_ttl=900)
    first = cached.get_fundamentals("AAPL")
    assert cached.get_fundamentals("AAPL") == first
    assert inner.calls == 1
    cached.get_fundamentals("TCS.NS")
    assert inner.calls == 2


def test_default_fundamentals_cache_is_fifteen_minutes():
    from app.config import Settings

    assert Settings().fundamentals_cache_ttl_seconds == 900
