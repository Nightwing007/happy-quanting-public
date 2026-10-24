"""Trading endpoints over HTTP. Fake prices: AAPL 230, MSFT 420, BTC-USD 60000, all USD.

Account starts with 100000 USD. Figures are worked out by hand beside each assertion.
"""

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.market_data.fake import FakeProvider

D = Decimal

# These tests are about the HTTP surface, not about what a broker charges.
pytestmark = pytest.mark.usefixtures("zero_costs")
BACKEND_DIR = Path(__file__).resolve().parent.parent


def order(client: TestClient, symbol: str = "AAPL", side: str = "buy", quantity: str = "10", **extra):
    return client.post("/api/orders", json={"symbol": symbol, "side": side, "quantity": quantity, **extra})


def test_market_buy_shows_in_portfolio(client: TestClient):
    response = order(client, "AAPL", quantity="10")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "filled"
    assert body["quantity"] == "10"
    # 10 x 230 = 2300.00 spent
    assert body["amount"] == "2300.00"

    portfolio = client.get("/api/portfolio").json()
    # 100000 - 2300 = 97700; the shares are worth 2300 at an unchanged price
    assert D(portfolio["cash"]) == D("97700")
    assert portfolio["market_value"] == "2300.00"
    assert D(portfolio["total_value"]) == D("100000")
    [holding] = portfolio["holdings"]
    assert holding["symbol"] == "AAPL"
    assert holding["direction"] == "long"
    assert holding["quantity"] == "10"
    [trade] = portfolio["trades"]
    assert trade["open_quantity"] == "10"


def test_rejected_orders_return_a_readable_400(client: TestClient):
    # 1000 x 230 = 230000 > 100000 cash
    too_big = order(client, "AAPL", quantity="1000")
    assert too_big.status_code == 400
    # Selling something never bought, where shorting isn't offered (Germany)
    not_held = order(client, "SAP.DE", side="sell", quantity="1")
    assert not_held.status_code == 400
    for response in (too_big, not_held):
        detail = response.json()["detail"]
        assert isinstance(detail, str)
        assert "Traceback" not in detail
        assert detail.endswith(".")
    assert "only have" in too_big.json()["detail"]
    assert client.get("/api/orders").json() == []


def test_quantity_must_be_a_string(client: TestClient):
    as_number = client.post("/api/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 10})
    assert as_number.status_code == 422
    assert isinstance(as_number.json()["detail"], str)
    assert "string" in as_number.json()["detail"]

    garbage = order(client, quantity="abc")
    assert garbage.status_code == 422
    assert "abc" in garbage.json()["detail"]

    bad_price = order(client, type="limit", limit_price="cheap")
    assert bad_price.status_code == 422
    assert "Limit price" in bad_price.json()["detail"]


def test_fractional_crypto_quantity_is_exact(client: TestClient):
    response = order(client, "BTC-USD", quantity="0.5")
    assert response.status_code == 200
    body = response.json()
    assert body["quantity"] == "0.5"
    # 0.5 x 60000 = 30000.00
    assert body["amount"] == "30000.00"


def test_limit_order_open_then_cancel(client: TestClient):
    # AAPL is at 230, so a buy limit at 100 cannot fill yet.
    placed = order(client, "AAPL", quantity="5", type="limit", limit_price="100").json()
    assert placed["status"] == "open"
    assert placed["limit_price"] == "100"

    open_orders = client.get("/api/orders", params={"status": "open"}).json()
    assert [o["id"] for o in open_orders] == [placed["id"]]

    cancelled = client.delete(f"/api/orders/{placed['id']}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.delete(f"/api/orders/{placed['id']}")
    assert again.status_code == 400
    assert "already cancelled" in again.json()["detail"]
    assert client.get("/api/orders", params={"status": "open"}).json() == []


def test_orders_filter_and_order(client: TestClient):
    order(client, "AAPL", quantity="1")
    order(client, "MSFT", quantity="2")
    order(client, "AAPL", quantity="3")

    everything = client.get("/api/orders").json()
    assert [o["quantity"] for o in everything] == ["3", "2", "1"]  # newest first

    # Symbols are cleaned like everywhere else, so lower case works
    aapl = client.get("/api/orders", params={"symbol": "aapl"}).json()
    assert [o["quantity"] for o in aapl] == ["3", "1"]

    assert len(client.get("/api/orders", params={"limit": 1}).json()) == 1
    assert client.get("/api/orders", params={"limit": 0}).status_code == 422
    assert client.get("/api/orders", params={"limit": 501}).status_code == 422
    assert client.get("/api/orders", params={"status": "bogus"}).status_code == 422


def test_reset_restores_cash_and_clears_orders(client: TestClient):
    order(client, "AAPL", quantity="10")
    reset = client.post("/api/portfolio/reset")
    assert reset.status_code == 200
    body = reset.json()
    assert D(body["cash"]) == D("100000")
    assert body["holdings"] == [] and body["trades"] == []
    assert client.get("/api/orders").json() == []


def test_watchlist_lifecycle(client: TestClient):
    start = client.get("/api/watchlist").json()
    assert [i["symbol"] for i in start] == ["AAPL", "RELIANCE.NS", "BTC-USD", "^GSPC"]
    aapl = start[0]
    assert aapl["price"] == "230"
    # previous close is 99% of 230 = 227.7, so the change is 2.3 (1.01%)
    assert D(aapl["change"]) == D("2.3")
    assert aapl["currency"] == "USD"

    added = client.post("/api/watchlist", json={"symbol": "msft"})
    assert added.status_code == 200
    assert added.json()["symbol"] == "MSFT"
    again = client.post("/api/watchlist", json={"symbol": "MSFT"})
    assert again.status_code == 200
    symbols = [i["symbol"] for i in client.get("/api/watchlist").json()]
    assert symbols.count("MSFT") == 1

    unknown = client.post("/api/watchlist", json={"symbol": "NOPE"})
    assert unknown.status_code == 404
    assert isinstance(unknown.json()["detail"], str)

    removed = client.delete("/api/watchlist", params={"symbol": "^GSPC"})
    assert removed.status_code == 204
    assert "^GSPC" not in [i["symbol"] for i in client.get("/api/watchlist").json()]

    missing = client.delete("/api/watchlist", params={"symbol": "^GSPC"})
    assert missing.status_code == 404
    assert "not on your watchlist" in missing.json()["detail"]


def test_watchlist_missing_quote_gives_nulls(client: TestClient, fake_provider: FakeProvider):
    client.get("/api/watchlist")  # creates the account and starter list
    original = fake_provider.get_quote

    def flaky(symbol: str):
        if symbol == "BTC-USD":
            from app.market_data.base import DataUnavailable

            raise DataUnavailable()
        return original(symbol)

    fake_provider.get_quote = flaky  # type: ignore[method-assign]
    items = {i["symbol"]: i for i in client.get("/api/watchlist").json()}
    assert items["BTC-USD"]["price"] is None
    assert items["BTC-USD"]["currency"] is None
    assert items["AAPL"]["price"] == "230"


def test_openapi_lists_trading_paths(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    wanted = ["/api/portfolio", "/api/portfolio/reset", "/api/orders", "/api/orders/{order_id}"]
    for path in [*wanted, "/api/watchlist"]:
        assert path in paths


def test_export_openapi_script(tmp_path: Path):
    target = tmp_path / "openapi.json"
    result = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts" / "export_openapi.py"), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "/api/orders" in target.read_text(encoding="utf-8")


def test_trading_errors_carry_a_stable_code(client: TestClient):
    # Clients branch on `code`; the sentence may be reworded without breaking them.
    short = client.post("/api/orders/preview", json={"symbol": "SAP.DE", "side": "sell", "quantity": "1"})
    assert short.status_code == 400
    assert short.json()["code"] == "short_not_offered"
    missing = client.post("/api/trades/9999/exit/preview", json={})
    assert missing.json()["code"] == "trade_not_found"


def test_exit_orders_are_marked_as_exits_and_trades_carry_a_timezone(client: TestClient):
    assert order(client, "BTC-USD", quantity="0.1").status_code == 200
    plain_sell = order(client, "BTC-USD", side="sell", quantity="0.02").json()
    assert plain_sell["origin"] == "user"

    trades = client.get("/api/trades", params={"status": "open"}).json()
    assert trades[0]["timezone"] == "UTC"  # crypto has no exchange clock
    exited = client.post(f"/api/trades/{trades[0]['id']}/exit", json={})
    assert exited.status_code == 200
    assert exited.json()["origin"] == "exit"


def test_indian_trades_report_the_exchange_timezone(client: TestClient):
    assert order(client, "RELIANCE.NS", quantity="1").status_code == 200
    trades = client.get("/api/trades").json()
    assert trades[0]["timezone"] == "Asia/Kolkata"
