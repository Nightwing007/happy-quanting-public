"""Market hours, waiting orders, quantity steps and the rupee account.

Tests marked `real_calendar` use the real exchange calendars; every other test treats all
markets as open (autouse fixture in conftest). The clock is pinned with `at(...)`, UTC in,
and each test says the exchange-local time beside it. Fake prices: RELIANCE.NS 1250 INR,
AAPL 230 USD, 0700.HK 380 HKD, BTC-USD 60000, USDINR=X 83.5.
"""

import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.config import Settings
from app.market_data.base import DataUnavailable
from app.market_data.fake import FakeProvider
from app.models import Order, OrderStatus, OrderType, Trade
from app.trading import engine, hours, markets
from app.trading.errors import InsufficientFunds, InvalidOrder

D = Decimal
real_calendar = pytest.mark.real_calendar


def at(monkeypatch: pytest.MonkeyPatch, *args: int) -> datetime:
    when = datetime(*args, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: when)
    return when


def buy(db: Session, provider: FakeProvider, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        db, provider, symbol=symbol, side="buy", type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def inr_account(db: Session) -> None:
    account = engine.get_account(db)
    account.currency = "INR"
    account.cash = account.starting_cash = D("1000000")
    db.commit()


def status(code: str, *when: int) -> hours.MarketStatus:
    return hours.market_status(markets.MARKETS[code], datetime(*when, tzinfo=UTC))


# --- the calendars -------------------------------------------------------------------------


def test_every_market_has_a_calendar_that_exists():
    import exchange_calendars as xcals

    known = set(xcals.get_calendar_names())
    for market in markets.MARKETS.values():
        assert market.calendar == "24/7" or market.calendar in known, market.code


@real_calendar
def test_saturday_an_nse_order_waits_then_fills_monday_at_the_open(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # Saturday 2026-03-07 11:30 IST (06:00 UTC): NSE is shut for the weekend.
    at(monkeypatch, 2026, 3, 7, 6, 0)
    s = status("NSE", 2026, 3, 7, 6, 0)
    assert (s.state, s.is_open, s.reason) == ("closed", False, "weekend")
    order = buy(db, fake_provider, "RELIANCE.NS", "10")
    assert order.status == OrderStatus.OPEN  # a market order, accepted and waiting
    assert engine.get_account(db).cash == D("100000")  # nothing spent yet
    assert engine.fill_open_orders(db, fake_provider) == 0

    # Monday 2026-03-09 09:14 IST (03:44 UTC): still a minute before the open.
    at(monkeypatch, 2026, 3, 9, 3, 44)
    assert engine.fill_open_orders(db, fake_provider) == 0
    # Monday 09:15 IST (03:45 UTC): open, and the fake stamps its quote with the clock.
    at(monkeypatch, 2026, 3, 9, 3, 45)
    assert engine.fill_open_orders(db, fake_provider) == 1
    db.refresh(order)
    assert order.status == OrderStatus.FILLED
    # 10 x 1250 = 12500 INR; the account is USD, so 12500 x 0.011976 = 149.70 (zero costs)
    assert order.amount == D("149.70")


@real_calendar
def test_a_holiday_waits(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # Monday 2026-01-26 is Republic Day: XBOM has no session that day (checked in the
    # installed calendar). 10:30 IST (05:00 UTC), a time the market would otherwise be open.
    at(monkeypatch, 2026, 1, 26, 5, 0)
    s = status("NSE", 2026, 1, 26, 5, 0)
    assert (s.state, s.reason) == ("closed", "holiday")
    order = buy(db, fake_provider, "RELIANCE.NS", "1")
    assert order.status == OrderStatus.OPEN
    # Tuesday 2026-01-27 09:15 IST = 03:45 UTC
    at(monkeypatch, 2026, 1, 27, 3, 45)
    assert engine.fill_open_orders(db, fake_provider) == 1


@real_calendar
def test_hong_kong_lunch_break(fixed_clock):
    # Monday 2026-03-02, HKT = UTC+8. Morning session 09:30-12:00, afternoon 13:00-16:00.
    assert status("HKEX", 2026, 3, 2, 3, 59).is_open  # 11:59 HKT
    lunch = status("HKEX", 2026, 3, 2, 4, 30)  # 12:30 HKT
    assert (lunch.is_open, lunch.reason) == (False, "lunch break")
    assert (lunch.next_open.hour, lunch.next_open.minute) == (13, 0)
    assert status("HKEX", 2026, 3, 2, 5, 1).is_open  # 13:01 HKT
    market = markets.MARKETS["HKEX"]
    assert hours.status_label(market, lunch, datetime(2026, 3, 2, 4, 30, tzinfo=UTC)) == (
        "Lunch break · reopens 13:00 HKT"
    )


@real_calendar
def test_us_order_after_the_close_waits_and_fills_next_morning(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # Monday 2026-03-02, 16:30 EST (21:30 UTC); the close was 16:00 EST. DST starts on
    # 2026-03-08, so New York is still UTC-5 here.
    at(monkeypatch, 2026, 3, 2, 21, 30)
    order = buy(db, fake_provider, "AAPL", "10")
    assert order.status == OrderStatus.OPEN
    # Tuesday 2026-03-03 09:29 EST (14:29 UTC): not yet.
    at(monkeypatch, 2026, 3, 3, 14, 29)
    assert engine.fill_open_orders(db, fake_provider) == 0
    # 09:30 EST (14:30 UTC): the open.
    at(monkeypatch, 2026, 3, 3, 14, 30)
    assert engine.fill_open_orders(db, fake_provider) == 1
    db.refresh(order)
    assert (order.status, order.amount) == (OrderStatus.FILLED, D("2300.00"))  # 10 x 230


@real_calendar
def test_a_stale_quote_does_not_fill_even_when_the_market_is_open(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # Monday 2026-03-02 10:30 IST (05:00 UTC): NSE open since 09:15 IST (03:45 UTC).
    now = at(monkeypatch, 2026, 3, 2, 5, 0)
    # A quote stamped Friday 2026-02-27 15:30 IST (10:00 UTC): yesterday's close.
    friday = int(datetime(2026, 2, 27, 10, 0, tzinfo=UTC).timestamp())
    fake_provider.set_as_of("RELIANCE.NS", friday)
    order = buy(db, fake_provider, "RELIANCE.NS", "1")
    assert order.status == OrderStatus.OPEN
    assert engine.fill_open_orders(db, fake_provider) == 0
    fake_provider.set_as_of("RELIANCE.NS", int(now.timestamp()))
    assert engine.fill_open_orders(db, fake_provider) == 1


@real_calendar
def test_past_the_calendar_hours_are_unknown_and_trading_is_allowed(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # 2040-03-02 is far beyond the XBOM holiday list.
    at(monkeypatch, 2040, 3, 2, 5, 0)
    s = status("NSE", 2040, 3, 2, 5, 0)
    assert (s.state, s.is_open) == ("unknown", False)
    assert hours.is_open(markets.MARKETS["NSE"])  # unknown counts as open
    assert hours.status_label(markets.MARKETS["NSE"], s) == "Hours unknown"
    assert buy(db, fake_provider, "RELIANCE.NS", "1").status == OrderStatus.FILLED


@real_calendar
def test_crypto_is_always_open(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch, zero_costs
):
    # Sunday 2026-03-08 03:00 UTC
    at(monkeypatch, 2026, 3, 8, 3, 0)
    s = status("CRYPTO", 2026, 3, 8, 3, 0)
    assert (s.state, s.is_open) == ("open", True)
    assert hours.status_label(markets.MARKETS["CRYPTO"], s) == "Open 24/7"
    assert buy(db, fake_provider, "BTC-USD", "0.01").status == OrderStatus.FILLED


@real_calendar
def test_labels_read_in_the_exchange_timezone(fixed_clock):
    nse, hk, us = markets.MARKETS["NSE"], markets.MARKETS["HKEX"], markets.MARKETS["US"]

    def label(market: markets.Market, when: datetime) -> str:
        return hours.status_label(market, hours.market_status(market, when), when)

    # NSE open: Monday 2026-03-02 10:30 IST (05:00 UTC); closes 15:30 IST
    assert label(nse, datetime(2026, 3, 2, 5, 0, tzinfo=UTC)) == "Market open · closes 15:30 IST"
    # NSE on Saturday 2026-03-07: reopens Monday 09:15 IST
    assert label(nse, datetime(2026, 3, 7, 6, 0, tzinfo=UTC)) == "Market closed · opens Mon 09:15 IST"
    # Hong Kong Monday 10:30 HKT (02:30 UTC): the morning session ends at 12:00 HKT
    assert label(hk, datetime(2026, 3, 2, 2, 30, tzinfo=UTC)) == "Market open · closes 12:00 HKT"
    # New York at 10:00 local: winter 2026-03-02 (EST), summer 2026-06-15 (EDT)
    assert label(us, datetime(2026, 3, 2, 15, 0, tzinfo=UTC)) == "Market open · closes 16:00 EST"
    assert label(us, datetime(2026, 6, 15, 14, 0, tzinfo=UTC)) == "Market open · closes 16:00 EDT"


@real_calendar
def test_quote_api_carries_the_market_status(client: TestClient, fixed_clock, monkeypatch):
    at(monkeypatch, 2026, 3, 7, 6, 0)  # Saturday 11:30 IST
    body = client.get("/api/market/quote", params={"symbol": "RELIANCE.NS"}).json()
    m = body["market"]
    assert (m["code"], m["state"], m["is_open"], m["timezone"]) == ("NSE", "closed", False, "Asia/Kolkata")
    assert m["label"] == "Market closed · opens Mon 09:15 IST"
    assert m["next_open"].startswith("2026-03-09T09:15:00+05:30")
    assert m["quantity_step"] == "1"
    # an index has no market; the chart still works
    assert client.get("/api/market/quote", params={"symbol": "^NSEI"}).json()["market"] is None


@real_calendar
def test_closed_order_goes_through_the_api_as_open(client: TestClient, fixed_clock, monkeypatch, zero_costs):
    at(monkeypatch, 2026, 3, 7, 6, 0)
    response = client.post("/api/orders", json={"symbol": "RELIANCE.NS", "side": "buy", "quantity": "1"})
    assert response.status_code == 200
    assert response.json()["status"] == "open"


@real_calendar
def test_a_waiting_order_is_still_validated(
    db: Session, fake_provider: FakeProvider, fixed_clock, monkeypatch: pytest.MonkeyPatch
):
    at(monkeypatch, 2026, 3, 7, 6, 0)  # Saturday, NSE shut
    # The account holds 100000 USD (about 8.3 million INR); 10,000 x 1250 INR = 12.5 million INR
    with pytest.raises(InsufficientFunds):
        buy(db, fake_provider, "RELIANCE.NS", "10000")
    assert db.scalar(select(Order.id)) is None
    with pytest.raises(InvalidOrder):
        buy(db, fake_provider, "RELIANCE.NS", "0.5")


# --- quantity steps ------------------------------------------------------------------------


def test_quantity_steps(db: Session, fake_provider: FakeProvider, zero_costs):
    with pytest.raises(InvalidOrder, match=r"Indian shares trade in whole numbers\."):
        buy(db, fake_provider, "RELIANCE.NS", "0.5")
    assert buy(db, fake_provider, "AAPL", "0.0001").status == OrderStatus.FILLED
    with pytest.raises(InvalidOrder, match=r"US shares trade in steps of 0\.0001\."):
        buy(db, fake_provider, "AAPL", "0.00005")
    assert buy(db, fake_provider, "BTC-USD", "0.00000001").status == OrderStatus.FILLED


def test_steps_serialize_without_scientific_notation(client: TestClient, zero_costs):
    response = client.post("/api/orders", json={"symbol": "BTC-USD", "side": "buy", "quantity": "0.00000001"})
    assert response.status_code == 200
    assert response.json()["quantity"] == "0.00000001"
    steps = {
        s: client.get("/api/market/quote", params={"symbol": s}).json()["market"]["quantity_step"]
        for s in ("BTC-USD", "AAPL", "RELIANCE.NS")
    }
    assert steps == {"BTC-USD": "0.00000001", "AAPL": "0.0001", "RELIANCE.NS": "1"}
    refused = client.post("/api/orders", json={"symbol": "RELIANCE.NS", "side": "buy", "quantity": "0.5"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Indian shares trade in whole numbers."


# --- rupees --------------------------------------------------------------------------------


def test_defaults_are_a_rupee_account_with_ten_lakh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BASE_CURRENCY")
    monkeypatch.delenv("STARTING_CASH")
    settings = Settings(_env_file=None)
    assert (settings.base_currency, settings.starting_cash) == ("INR", D("1000000"))


def test_inr_account_pays_an_fx_line_on_foreign_shares_only(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    apple = buy(db, fake_provider, "AAPL", "1")  # IBKR, a USD stock in a rupee account
    # 230 USD x 83.5 = 19205.00 INR; the conversion markup is a line of its own
    assert apple.amount == D("19205.00")
    fx = [c for c in apple.charges if c["category"] == "fx"]
    assert len(fx) == 1 and fx[0]["native_currency"] == "USD"
    reliance = buy(db, fake_provider, "RELIANCE.NS", "1")  # Groww, rupees
    assert [c for c in reliance.charges if c["category"] == "fx"] == []
    assert reliance.fx_rate == D(1)


def inr(value: Decimal) -> Decimal:
    """A USD figure at 83.5 INR per dollar, 2 dp, half up."""
    return (value * D("83.5")).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def test_convert_account_currency(
    db: Session, fake_provider: FakeProvider, caplog: pytest.LogCaptureFixture
):
    # A USD account with real charges: buy 10 AAPL and 2 RELIANCE.NS, then sell 4 AAPL.
    first = buy(db, fake_provider, "AAPL", "10")
    engine.place_order(db, fake_provider, symbol="AAPL", side="sell", type="market", quantity=D("4"))
    buy(db, fake_provider, "RELIANCE.NS", "2")
    account = engine.get_account(db)
    cash, pnl = account.cash, account.realized_pnl
    before = {
        o.id: (o.amount, o.charges_total, o.realized_pnl, [D(c["amount"]) for c in o.charges])
        for o in db.scalars(select(Order))
    }
    basis = {t.symbol: t.cost_basis for t in db.scalars(select(Trade))}
    first_id = first.id
    assert pnl != 0 and len(before[first_id][3]) >= 1

    with caplog.at_level(logging.INFO, logger="app.trading.engine"):
        assert engine.convert_account_currency(db, fake_provider, "INR") is True
    # 98,587.94 x 83.5 = 8,232,092.99 (cash after the three trades and their charges)
    assert "Converted account from USD to INR at 83.50: cash 98,587.94 → 8,232,092.99" in caplog.text

    db.expire_all()
    account = engine.get_account(db)
    assert account.currency == "INR"
    assert account.starting_cash == D("8350000.00")  # 100000 x 83.5
    assert (account.cash, account.realized_pnl) == (inr(cash), inr(pnl))
    orders = list(db.scalars(select(Order)))
    assert len(orders) == 3
    for order in orders:
        amount, total, realized, line_amounts = before[order.id]
        assert order.amount == inr(amount) and order.charges_total == inr(total)
        assert order.realized_pnl == (inr(realized) if realized is not None else None)
        assert [D(c["amount"]) for c in order.charges] == [inr(a) for a in line_amounts]
    opening = db.get(Order, first_id)
    assert opening.amount == D("192050.00")  # 10 x 230 x 83.5
    assert opening.fx_rate == D("83.5")  # USD -> INR; it was 1 in the dollar account
    reliance = next(o for o in orders if o.symbol == "RELIANCE.NS")
    assert reliance.fx_rate == D(1)  # rupee shares in a rupee account
    for trade in db.scalars(select(Trade)):
        assert trade.cost_basis == inr(basis[trade.symbol])
    assert engine.convert_account_currency(db, fake_provider, "INR") is False  # already done


def test_convert_account_currency_leaves_the_account_alone_without_a_rate(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch, caplog
):
    buy(db, fake_provider, "AAPL", "1")
    cash = engine.get_account(db).cash

    def no_rate(symbol: str):
        raise DataUnavailable()

    monkeypatch.setattr(fake_provider, "get_quote", no_rate)
    with caplog.at_level(logging.WARNING, logger="app.trading.engine"):
        assert engine.convert_account_currency(db, fake_provider, "INR") is False
    assert "Leaving the account unchanged" in caplog.text
    account = engine.get_account(db)
    assert (account.currency, account.cash) == ("USD", cash)
