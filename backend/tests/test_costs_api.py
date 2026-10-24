"""Preview, settings and brokers endpoints, with real fee schedules (no zero_costs).

Fake prices: AAPL 230 USD, VOD.L 0.72 GBP. USD account, default broker Interactive Brokers.
"""

from decimal import Decimal

from fastapi.testclient import TestClient

D = Decimal


def preview(client: TestClient, symbol: str = "AAPL", side: str = "buy", quantity: str = "10", **extra):
    return client.post(
        "/api/orders/preview", json={"symbol": symbol, "side": side, "quantity": quantity, **extra}
    )


def order(client: TestClient, symbol: str = "AAPL", side: str = "buy", quantity: str = "10", **extra):
    return client.post("/api/orders", json={"symbol": symbol, "side": side, "quantity": quantity, **extra})


def test_preview_of_a_market_buy(client: TestClient):
    body = preview(client).json()
    # 10 x 230 = 2300.00. IBKR: 10 x 0.005 = 0.05, lifted to the $1 minimum -> 1.00.
    # cash change -(2300 + 1.00) = -2301.00
    assert body["value"] == "2300.00"
    assert body["currency"] == "USD"
    assert body["fx_rate"] == "1"
    assert body["value_account"] == "2300.00"
    assert body["price"] == "230"
    assert body["charges_total"] == "1.00"
    assert body["cash_change"] == "-2301.00"
    assert [(c["name"], c["category"], c["amount"]) for c in body["charges"]] == [
        ("Brokerage (US)", "brokerage", "1.00")
    ]
    assert body["charges"][0]["description"]
    assert body["broker"] == {"code": "ibkr", "name": "Interactive Brokers"}
    assert body["market"] == {"code": "US", "name": "US"}


def test_preview_of_a_sell_needs_no_holdings(client: TestClient):
    body = preview(client, side="sell", quantity="5").json()
    # Nothing is held, so the sell is a short of 5 (US, margin product). 5 x 230 = 1150.
    # Brokerage: 5 x 0.005 = 0.025 -> $1 minimum, under the 1% cap (11.50) -> 1.00.
    # SEC fee 0.00206% x 1150 = 0.02369 = 0.02. Charges 1.02. The proceeds are not paid out:
    # cash change is -1.02 and 50% x 1150 = 575.00 is blocked as margin.
    assert body["charges_total"] == "1.02"
    assert body["cash_change"] == "-1.02"
    assert body["margin_change"] == "575.00"
    [leg] = body["legs"]
    assert (leg["kind"], leg["product"], leg["quantity"]) == ("open_short", "margin", "5")
    assert leg["trade_id"] is None


def test_preview_prices_a_resting_limit_at_its_limit_and_a_marketable_one_at_the_market(client: TestClient):
    resting = preview(client, type="limit", limit_price="200").json()
    # 10 x 200 = 2000 (the limit rests below the 230 market); brokerage 1.00
    assert (resting["price"], resting["value"], resting["cash_change"]) == ("200", "2000.00", "-2001.00")
    marketable = preview(client, type="limit", limit_price="240").json()
    # a limit above the market fills at the market price, 230, not at 240
    assert (marketable["price"], marketable["value"]) == ("230", "2300.00")


def test_preview_equals_the_filled_order(client: TestClient):
    quoted = preview(client, quantity="25").json()
    placed = order(client, quantity="25").json()
    # 25 x 230 = 5750; brokerage 25 x 0.005 = 0.125 -> $1 minimum -> 1.00; CAT fee rounds to nothing
    assert placed["charges"] == quoted["charges"]
    assert placed["charges_total"] == quoted["charges_total"] == "1.00"
    assert placed["amount"] == quoted["value_account"] == "5750.00"
    cash = D(client.get("/api/portfolio").json()["cash"])
    assert cash == D("100000") + D(quoted["cash_change"]) == D("94249.00")


def test_order_list_carries_the_charges(client: TestClient):
    order(client, quantity="10")
    [row] = client.get("/api/orders").json()
    assert row["charges_total"] == "1.00"
    assert row["charges"][0]["name"] == "Brokerage (US)"
    assert row["charges"][0]["native_currency"] == "USD"
    # an order that is still waiting has been charged nothing
    waiting = order(client, quantity="1", type="limit", limit_price="100").json()
    assert (waiting["charges"], waiting["charges_total"]) == ([], "0")


def test_portfolio_reports_charges_paid_and_break_even(client: TestClient):
    order(client, quantity="10")
    body = client.get("/api/portfolio").json()
    assert body["charges_paid"]["total"] == "1.00"
    assert body["charges_paid"]["by_category"]["brokerage"] == "1.00"
    assert body["charges_paid"]["by_category"]["tax"] == "0"
    assert set(body["charges_paid"]["by_category"]) == {
        "brokerage", "tax", "exchange", "regulatory", "depository", "gst", "fx",
    }  # fmt: skip
    [position] = body["holdings"]
    # cost 2300 + 1.00 = 2301.00; selling 10 pays brokerage 1.00 plus the SEC fee (0.00206%).
    # At 230.20: 2302.00 - 1.00 - 0.05 (SEC 0.0474) = 2300.95, short of 2301.00.
    # At 230.21: 2302.10 - 1.00 - 0.05 (SEC 0.0474) = 2301.05, enough. So 230.21.
    assert position["break_even_price"] == "230.21"
    assert D(body["total_pnl"]) == D("-1.00")  # the entry charge, felt at once
    assert D(body["unrealized_pnl"]) == D("-1.00")


def test_preview_refuses_a_market_the_broker_does_not_offer(client: TestClient):
    assert client.put("/api/settings", json={"broker_international": "vested"}).status_code == 200
    response = preview(client, "VOD.L")
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Vested only offers US stocks. Choose Interactive Brokers in Settings to trade London shares."
    )
    assert order(client, "VOD.L").status_code == 400
    assert client.get("/api/orders").json() == []


def test_preview_validation_errors_are_readable_sentences(client: TestClient):
    response = client.post("/api/orders/preview", json={"symbol": "AAPL", "side": "buy", "quantity": 10})
    assert response.status_code == 422
    assert "string" in response.json()["detail"]
    assert preview(client, quantity="0").status_code == 400
    assert preview(client, "^GSPC").status_code == 400  # an index can't be traded or costed
    assert preview(client, "NOPE").status_code == 404


def test_settings_default_and_update(client: TestClient):
    assert client.get("/api/settings").json() == {
        "broker_india": "groww",
        "broker_international": "ibkr",
        "broker_crypto": "coindcx",
    }
    updated = client.put("/api/settings", json={"broker_india": "zerodha", "broker_crypto": "binance"})
    assert updated.status_code == 200
    assert updated.json() == {
        "broker_india": "zerodha",
        "broker_international": "ibkr",
        "broker_crypto": "binance",
    }
    assert client.get("/api/settings").json()["broker_india"] == "zerodha"


def test_settings_put_validates_the_segment(client: TestClient):
    wrong_segment = client.put("/api/settings", json={"broker_india": "ibkr"})
    assert wrong_segment.status_code == 400
    assert "isn't a broker for Indian stocks" in wrong_segment.json()["detail"]
    assert client.put("/api/settings", json={"broker_crypto": "zerodha"}).status_code == 400
    assert client.put("/api/settings", json={"broker_international": "nope"}).status_code == 400
    # a bad choice alongside a good one applies neither
    mixed = client.put("/api/settings", json={"broker_international": "vested", "broker_india": "ibkr"})
    assert mixed.status_code == 400
    assert client.get("/api/settings").json()["broker_international"] == "ibkr"


def test_brokers_are_grouped_by_segment(client: TestClient):
    groups = client.get("/api/brokers").json()
    assert [g["segment"] for g in groups] == ["india", "international", "crypto"]
    counts = {g["segment"]: len(g["brokers"]) for g in groups}
    assert counts == {"india": 5, "international": 3, "crypto": 5}
    india = {b["code"]: b for b in groups[0]["brokers"]}
    assert [m["code"] for m in india["groww"]["markets"]] == ["NSE", "BSE"]
    assert india["groww"]["name"] == "Groww" and india["groww"]["notes"]
    vested = next(b for b in groups[1]["brokers"] if b["code"] == "vested")
    assert [m["code"] for m in vested["markets"]] == ["US"]
    ibkr = next(b for b in groups[1]["brokers"] if b["code"] == "ibkr")
    assert ibkr["fx_markup_percent"] == "0.03"
    assert len(ibkr["markets"]) > 20


def test_openapi_lists_the_new_paths(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/orders/preview", "/api/settings", "/api/brokers"):
        assert path in paths
