"""The payouts report: closed trades with the charges at both ends, read from the orders' legs.

Fake prices: AAPL 230 USD, BTC-USD 60000. The account is USD (conftest). Tests that need exact
figures use `zero_costs`; the rest compare the report with the orders' own recorded charges, so
no fee arithmetic is repeated here.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.market_data.fake import FakeProvider
from app.models import Order, OrderSide, OrderType
from app.trading import engine
from tests.helpers import live

D = Decimal


def place(db: Session, provider: FakeProvider, symbol: str, side: str, qty: str) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide(side), type=OrderType.MARKET, quantity=D(qty)
    )


def lines(raw: list[dict]) -> dict[str, str]:
    return {c["name"]: c["amount"] for c in raw}


def test_no_closed_trades_is_an_empty_report(client: TestClient):
    body = client.get("/api/payouts").json()
    assert body["payouts"] == []
    assert body["currency"] == "USD"
    assert body["totals"] == {
        "trades_closed": 0, "brought_in": "0", "charges": "0", "financing": "0", "net_profit": "0",
    }  # fmt: skip


def test_an_open_trade_is_not_a_payout(client: TestClient):
    client.post("/api/orders", json={"symbol": "AAPL", "side": "buy", "quantity": "2"})
    assert client.get("/api/payouts").json()["payouts"] == []


@pytest.mark.usefixtures("zero_costs")
def test_a_long_that_gained(db: Session, fake_provider: FakeProvider):
    place(db, fake_provider, "AAPL", "buy", "2")  # 2 x 230 = 460 in
    fake_provider.set_price("AAPL", D("250"))
    place(db, fake_provider, "AAPL", "sell", "2")  # 2 x 250 = 500 out, no charges
    report = engine.get_payouts(live(db, FakeProvider()))
    [p] = report.payouts
    assert (p.entry_value, p.exit_value, p.brought_in) == (D("460"), D("500"), D("500"))
    assert p.realized_pnl == D("40")  # 500 - 460
    assert (p.closed_how, p.direction) == ("sell", "long")
    assert report.totals.net_profit == D("40") and report.totals.trades_closed == 1


def test_charge_lines_at_both_ends_match_the_orders(client: TestClient):
    buy = client.post("/api/orders", json={"symbol": "BTC-USD", "side": "buy", "quantity": "1"}).json()
    first = client.post("/api/trades/1/exit", json={"quantity": "0.4"}).json()
    last = client.post("/api/trades/1/exit").json()
    [p] = client.get("/api/payouts").json()["payouts"]
    assert p["trade_id"] == 1 and p["closed_how"] == "exit"
    # Entry lines are the buy order's, though the trade's own entry_charges fell to zero on exit.
    assert lines(p["entry_charge_lines"]) == lines(buy["charges"])
    assert D(p["entry_charges_total"]) == D(buy["charges_total"]) > 0
    # Two exits: each line is the two orders' amounts added.
    for name, amount in lines(p["exit_charge_lines"]).items():
        parts = [D(c["amount"]) for o in (first, last) for c in o["charges"] if c["name"] == name]
        assert D(amount) == sum(parts)
    assert D(p["exit_charges_total"]) == D(first["charges_total"]) + D(last["charges_total"])
    assert sum(D(c["amount"]) for c in p["exit_charge_lines"]) == D(p["exit_charges_total"])
    # Same price both ways: the profit is exactly minus what both ends cost.
    assert D(p["realized_pnl"]) == -(D(p["entry_charges_total"]) + D(p["exit_charges_total"]))
    assert p["timezone"] == "UTC"


def test_selling_more_than_held_gives_a_long_and_a_short_payout(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    client.post("/api/orders", json={"symbol": "BTC-USD", "side": "buy", "quantity": "1"})
    sold = client.post("/api/orders", json={"symbol": "BTC-USD", "side": "sell", "quantity": "2"}).json()
    short_id = next(leg["trade_id"] for leg in sold["legs"] if leg["kind"] == "open_short")
    fake_provider.set_price("BTC-USD", D("59000"))
    client.post(f"/api/trades/{short_id}/exit")
    body = client.get("/api/payouts").json()
    short, long = body["payouts"]  # newest close first
    assert (short["direction"], short["closed_how"], long["direction"], long["closed_how"]) == (
        "short", "exit", "long", "sell",
    )  # fmt: skip
    assert lines(long["exit_charge_lines"]) == lines(sold["legs"][0]["charges"])
    # The short sold 1 at 60000 and bought back at 59000: 1000 left before any charge.
    assert D(short["entry_value"]) == D("60000") and D(short["exit_value"]) == D("59000")
    assert D(short["brought_in"]) == D("1000")
    assert D(short["realized_pnl"]) == (
        D(short["brought_in"]) - D(short["entry_charges_total"]) - D(short["exit_charges_total"])
        - D(short["financing_paid"])
    )  # fmt: skip
    assert D(short["entry_charges_total"]) > 0
    totals = body["totals"]
    assert totals["trades_closed"] == 2
    assert D(totals["net_profit"]) == D(short["realized_pnl"]) + D(long["realized_pnl"])
    assert D(totals["charges"]) == sum(
        D(p[k]) for p in (short, long) for k in ("entry_charges_total", "exit_charges_total")
    )


def test_a_fired_stop_loss_is_badged_and_limit_trims_the_list_not_the_totals(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    for _ in range(2):
        client.post("/api/orders", json={"symbol": "BTC-USD", "side": "buy", "quantity": "0.5"})
    client.post("/api/trades/1/exit")
    client.put("/api/trades/2/protection", json={"stop_price": "59000"})
    fake_provider.set_price("BTC-USD", D("58000"))
    assert engine.trigger_protected_trades(live(db, fake_provider)) == 1
    payouts = client.get("/api/payouts").json()["payouts"]
    assert [(p["trade_id"], p["closed_how"]) for p in payouts] == [(2, "stop_loss"), (1, "exit")]
    assert D(payouts[0]["exit_value"]) == D("29000")  # 0.5 x 58000: fires at the market, not at the 59000 set
    trimmed = client.get("/api/payouts", params={"limit": 1}).json()
    assert len(trimmed["payouts"]) == 1 and trimmed["totals"]["trades_closed"] == 2
    assert client.get("/api/payouts", params={"limit": 0}).status_code == 422
