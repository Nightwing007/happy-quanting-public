from decimal import Decimal

import pytest

BARS = "/api/market/bars"


def test_bars_with_indicators(client):
    params = {"symbol": "AAPL", "interval": "1d", "range": "6mo", "indicators": "sma:20,rsi:14"}
    r = client.get(BARS, params=params)
    assert r.status_code == 200
    body = r.json()
    bars = body["bars"]
    assert bars
    assert body["currency"] == "USD"
    assert len(body["indicators"]) == 2
    sma, rsi = body["indicators"]
    assert (sma["pane"], sma["label"]) == ("price", "SMA 20")
    assert (rsi["pane"], rsi["label"]) == ("own", "RSI 14")
    # A 20-period SMA has no value for the first 19 bars.
    assert len(sma["points"]) == len(bars) - 19
    assert all(0 <= p["value"] <= 100 for p in rsi["points"])
    assert sma["points"][-1]["time"] == bars[-1]["time"]
    assert isinstance(bars[0]["close"], str)


def test_rsi_defaults_to_period_14(client):
    r = client.get(BARS, params={"symbol": "AAPL", "indicators": "rsi"})
    assert r.status_code == 200
    assert r.json()["indicators"][0]["period"] == 14


def test_bad_interval(client):
    r = client.get(BARS, params={"symbol": "AAPL", "interval": "2d"})
    assert r.status_code == 400
    assert "Interval '2d' isn't available" in r.json()["detail"]
    assert "1m, 5m" in r.json()["detail"]


def test_bad_range_for_interval(client):
    r = client.get(BARS, params={"symbol": "AAPL", "interval": "5m", "range": "5y"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Range '5y' isn't available for 5m bars. Choose one of: 1d, 5d, 1mo."


@pytest.mark.parametrize("spec", ["sma:1", "sma:401", "foo:3", "sma:abc", "sma", "sma:-5"])
def test_bad_indicators(client, spec):
    r = client.get(BARS, params={"symbol": "AAPL", "indicators": spec})
    assert r.status_code == 400
    assert r.json()["detail"]


def test_validation_happens_before_fetch(client, fake_provider):
    # Unknown symbol would be 404, but the bad interval must win without touching the provider.
    r = client.get(BARS, params={"symbol": "NOPE", "interval": "2d"})
    assert r.status_code == 400


def test_unknown_symbol_is_404_with_message(client):
    for path in ("/api/market/quote", BARS):
        r = client.get(path, params={"symbol": "NOPE"})
        assert r.status_code == 404
        assert r.json()["detail"].startswith("No market data found for 'NOPE'")


@pytest.mark.parametrize("symbol", ["^GSPC", "EURUSD=X", "RELIANCE.NS"])
def test_awkward_symbols_work_in_query(client, symbol):
    assert client.get("/api/market/quote", params={"symbol": symbol}).json()["symbol"] == symbol
    assert client.get(BARS, params={"symbol": symbol, "range": "1mo"}).status_code == 200


def test_symbol_is_normalised(client):
    assert client.get("/api/market/quote", params={"symbol": " aapl "}).json()["symbol"] == "AAPL"


def test_quote_change_and_json_strings(client, fake_provider):
    # AAPL previous close is 230 * 0.99 = 227.7. Price 240: change = 240 - 227.7 = 12.3,
    # percent = 12.3 / 227.7 * 100 = 5.40184... -> 5.40.
    fake_provider.set_price("AAPL", Decimal("240"))
    body = client.get("/api/market/quote", params={"symbol": "AAPL"}).json()
    assert body["price"] == "240"
    assert body["previous_close"] == "227.700000"
    assert body["change"] == "12.300000"
    assert body["change_percent"] == "5.40"
    assert isinstance(body["price"], str)
    assert body["tradable"] is True


def test_quote_tiny_decimal_is_not_scientific(client, fake_provider):
    fake_provider.set_price("INRUSD=X", Decimal("0.00000001"))
    assert client.get("/api/market/quote", params={"symbol": "INRUSD=X"}).json()["price"] == "0.00000001"


def test_index_is_not_tradable(client):
    assert client.get("/api/market/quote", params={"symbol": "^GSPC"}).json()["tradable"] is False


def test_search(client):
    hits = client.get("/api/market/search", params={"q": "reliance"}).json()
    assert "RELIANCE.NS" in [h["symbol"] for h in hits]
    assert client.get("/api/market/search", params={"q": ""}).status_code == 422


def test_openapi_lists_market_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/market/search", "/api/market/quote", "/api/market/bars"):
        assert path in paths


def test_health_reports_provider(client):
    body = client.get("/api/health").json()
    assert body["data_source"] == "fake"
    assert body["status"] == "ok"
