"""Stop-loss and target: setting them, validating them, and firing them.

Fake prices: RELIANCE.NS 1250 INR, AAPL 230 USD, BTC-USD 60000. Tests about the firing rules use
`zero_costs`; the ones about charges use Groww's real schedule. Every expected figure is worked
out beside the assertion; if one disagrees with the code, recompute it before touching the engine.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.market_data.fake import FakeProvider
from app.models import Order, OrderSide, OrderType, Trade
from app.trading import engine, hours
from app.trading.engine import live_context as live
from app.trading.errors import ProtectionInvalid, TradeNotFound, TradeNotOpen

D = Decimal


def buy(db: Session, provider: FakeProvider, symbol: str, qty: str) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.BUY, type=OrderType.MARKET, quantity=D(qty)
    )


def sell(db: Session, provider: FakeProvider, symbol: str, qty: str) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.SELL, type=OrderType.MARKET, quantity=D(qty)
    )


def inr_account(db: Session, cash: str = "1000000") -> None:
    account = engine.get_account(db)
    account.currency = "INR"
    account.cash = account.starting_cash = D(cash)
    db.commit()


def all_trades(db: Session) -> list[Trade]:
    return list(db.scalars(select(Trade).order_by(Trade.id)))


def all_orders(db: Session) -> list[Order]:
    return list(db.scalars(select(Order).order_by(Order.id)))


def protect(db, provider, trade: Trade, stop: str | None, target: str | None):
    return engine.set_protection(
        live(db, provider), trade.id, D(stop) if stop else None, D(target) if target else None
    )


def fire(db: Session, provider: FakeProvider) -> int:
    return engine.trigger_protected_trades(live(db, provider))


def assert_books_balance(db: Session, provider: FakeProvider) -> None:
    pf = engine.get_portfolio(live(db, provider))
    assert pf.realized_pnl + pf.unrealized_pnl == pf.total_pnl
    assert pf.available_cash == pf.cash - pf.margin_used
    assert pf.available_cash >= 0


@pytest.fixture
def long_reliance(db: Session, fake_provider: FakeProvider, zero_costs, fixed_clock) -> Trade:
    """10 RELIANCE.NS bought at 1250 with no charges: 12,500 spent, cash 987,500."""
    inr_account(db)
    buy(db, fake_provider, "RELIANCE.NS", "10")
    [trade] = all_trades(db)
    return trade


# --- firing -------------------------------------------------------------------------------


def test_stop_at_1200_fires_at_1195_and_not_at_1210(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade, fixed_clock: datetime
):
    protect(db, fake_provider, long_reliance, "1200", "1400")
    fake_provider.set_price("RELIANCE.NS", D("1210"))
    assert fire(db, fake_provider) == 0
    assert long_reliance.status == "open"

    fake_provider.set_price("RELIANCE.NS", D("1195"))
    assert fire(db, fake_provider) == 1
    # Sold 10 at 1195 = 11,950 (no charges). Cost was 12,500, so realized 11,950 - 12,500 = -550.
    assert long_reliance.status == "closed"
    assert long_reliance.exit_value == D("11950.00")
    assert long_reliance.realized_pnl == D("-550.00")
    assert engine.get_account(db).cash == D("999450.00")  # 987,500 + 11,950
    assert (long_reliance.closed_how, long_reliance.closed_at) == ("stop_loss", fixed_clock)
    [_, order] = all_orders(db)
    assert (order.origin, order.side, order.status) == ("stop_loss", "sell", "filled")
    assert order.trade_id == long_reliance.id
    assert "Stop-loss of ₹1,200.00 reached" in (order.note or "")
    assert_books_balance(db, fake_provider)


def test_one_firing_ends_the_other(db: Session, fake_provider: FakeProvider, long_reliance: Trade):
    protect(db, fake_provider, long_reliance, "1200", "1400")
    fake_provider.set_price("RELIANCE.NS", D("1195"))
    assert fire(db, fake_provider) == 1
    assert (long_reliance.stop_price, long_reliance.target_price, long_reliance.protection_expires_at) == (
        None, None, None,
    )  # fmt: skip
    orders_before = len(all_orders(db))
    # The price now runs up to the old target: nothing is left to fire.
    fake_provider.set_price("RELIANCE.NS", D("1400"))
    assert fire(db, fake_provider) == 0
    assert len(all_orders(db)) == orders_before


def test_target_fires_and_is_recorded_as_a_target(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    protect(db, fake_provider, long_reliance, "1200", "1400")
    fake_provider.set_price("RELIANCE.NS", D("1401"))
    assert fire(db, fake_provider) == 1
    # Sold 10 at 1401 = 14,010; 14,010 - 12,500 = +1,510.
    assert long_reliance.realized_pnl == D("1510.00")
    assert long_reliance.closed_how == "target"
    assert all_orders(db)[-1].origin == "target"
    assert long_reliance.stop_price is None  # the stop stops applying too


def test_gap_to_1100_fills_at_1100_not_at_the_stop(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    protect(db, fake_provider, long_reliance, "1200", None)
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    assert fire(db, fake_provider) == 1
    order = all_orders(db)[-1]
    assert order.fill_price == D("1100")
    # 10 x 1100 = 11,000; 11,000 - 12,500 = -1,500. Filling at the 1200 stop would have lost only 500.
    assert order.amount == D("11000.00")
    assert long_reliance.realized_pnl == D("-1500.00")


def test_gap_fill_with_real_charges_worked_out(
    db: Session, fake_provider: FakeProvider, fixed_clock: datetime
):
    inr_account(db)
    entry = buy(db, fake_provider, "RELIANCE.NS", "10")
    # Entry (Groww delivery buy) 12,500: brokerage 12.50, STT 12.50, stamp 1.88, NSE 0.38, SEBI 0.01,
    # GST 18% x (12.50 + 0.38 + 0.01) = 2.32  ->  29.59. Cost basis 12,529.59.
    assert entry.charges_total == D("29.59")
    [trade] = all_trades(db)
    protect(db, fake_provider, trade, "1200", None)
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    assert fire(db, fake_provider) == 1
    exit_order = all_orders(db)[-1]
    # Exit at 1100: value 11,000.00. Brokerage 11.00, STT 11.00, NSE 0.00307% = 0.3377 -> 0.34,
    # SEBI 0.011 -> 0.01, DP flat 20.00, GST 18% x (11.00 + 0.34 + 0.01 + 20.00) = 18% x 31.35 = 5.643 -> 5.64
    #   total 11.00 + 11.00 + 0.34 + 0.01 + 20.00 + 5.64 = 47.99
    assert exit_order.charges_total == D("47.99")
    assert exit_order.cash_change == D("10952.01")  # 11,000.00 - 47.99
    assert exit_order.realized_pnl == D("-1577.58")  # 10,952.01 - 12,529.59
    assert trade.realized_pnl == D("-1577.58")
    assert_books_balance(db, fake_provider)


def test_stop_is_checked_before_the_target(db: Session, fake_provider: FakeProvider, long_reliance: Trade):
    # A long's stop sits below its target and validation keeps it so, so one price can't reach
    # both. Force the crossed state directly to pin the order the code asks them in: on a gap
    # through both, the stop is what a broker hits first and you take the loss.
    long_reliance.stop_price, long_reliance.target_price = D("1200"), D("1000")
    long_reliance.protection_expires_at = clock.now() + timedelta(days=30)
    db.commit()
    fake_provider.set_price("RELIANCE.NS", D("900"))  # at or below both
    assert fire(db, fake_provider) == 1
    assert long_reliance.closed_how == "stop_loss"
    assert all_orders(db)[-1].origin == "stop_loss"


def test_short_stop_fires_upward_and_target_downward(db: Session, fake_provider: FakeProvider, zero_costs):
    sell(db, fake_provider, "AAPL", "10")  # short 10 at 230: takes in 2,300
    sell(db, fake_provider, "AAPL", "10")  # a second short, for the target
    stop_trade, target_trade = all_trades(db)
    protect(db, fake_provider, stop_trade, "250", None)
    protect(db, fake_provider, target_trade, None, "200")

    fake_provider.set_price("AAPL", D("249"))  # below the stop, above the target
    assert fire(db, fake_provider) == 0
    fake_provider.set_price("AAPL", D("251"))
    assert fire(db, fake_provider) == 1
    # Covered 10 at 251 = 2,510 against 2,300 taken in: 2,300 - 2,510 = -210.
    assert (stop_trade.status, stop_trade.closed_how, stop_trade.realized_pnl) == (
        "closed",
        "stop_loss",
        D("-210.00"),
    )
    assert all_orders(db)[-1].side == "buy"
    assert target_trade.status == "open"

    fake_provider.set_price("AAPL", D("199"))
    assert fire(db, fake_provider) == 1
    # Covered 10 at 199 = 1,990: 2,300 - 1,990 = +310.
    assert (target_trade.closed_how, target_trade.realized_pnl) == ("target", D("310.00"))
    assert_books_balance(db, fake_provider)


def test_nothing_fires_while_the_market_is_closed(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade, monkeypatch: pytest.MonkeyPatch
):
    protect(db, fake_provider, long_reliance, "1200", None)
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    monkeypatch.setattr(
        hours,
        "market_status",
        lambda market, at=None: hours.MarketStatus("closed", False, None, None, None, "UTC", "weekend"),
    )
    assert fire(db, fake_provider) == 0
    assert long_reliance.status == "open"
    assert long_reliance.stop_price == D("1200")  # still watching


def test_a_quote_from_before_this_session_does_not_fire(
    db: Session,
    fake_provider: FakeProvider,
    long_reliance: Trade,
    fixed_clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
):
    protect(db, fake_provider, long_reliance, "1200", None)
    session_open = fixed_clock - timedelta(hours=1)
    monkeypatch.setattr(
        hours,
        "market_status",
        lambda market, at=None: hours.MarketStatus("open", True, session_open, None, None, "UTC"),
    )
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    fake_provider.set_as_of(
        "RELIANCE.NS", int((session_open - timedelta(hours=1)).timestamp())
    )  # yesterday's
    assert fire(db, fake_provider) == 0
    assert long_reliance.status == "open"

    fake_provider.set_as_of("RELIANCE.NS", int(fixed_clock.timestamp()))  # a fresh one
    assert fire(db, fake_provider) == 1


def test_protection_lapses_after_a_year(
    db: Session,
    fake_provider: FakeProvider,
    long_reliance: Trade,
    fixed_clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
):
    protect(db, fake_provider, long_reliance, "1200", "1400")
    assert long_reliance.protection_expires_at == fixed_clock + timedelta(days=365)

    monkeypatch.setattr(clock, "now", lambda: fixed_clock + timedelta(days=364))
    fake_provider.set_price("RELIANCE.NS", D("1210"))
    assert fire(db, fake_provider) == 0
    assert long_reliance.stop_price == D("1200")  # one day left

    monkeypatch.setattr(clock, "now", lambda: fixed_clock + timedelta(days=365))
    fake_provider.set_price("RELIANCE.NS", D("1195"))  # would have fired a day earlier
    assert fire(db, fake_provider) == 0
    assert long_reliance.status == "open"
    assert (long_reliance.stop_price, long_reliance.target_price, long_reliance.protection_expires_at) == (
        None, None, None,
    )  # fmt: skip


def test_one_trade_failing_does_not_stop_the_others(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade, monkeypatch: pytest.MonkeyPatch
):
    buy(db, fake_provider, "RELIANCE.NS", "5")
    first, second = all_trades(db)
    protect(db, fake_provider, first, "1200", None)
    protect(db, fake_provider, second, "1200", None)
    real_fill = engine._fill
    calls = []

    def flaky_fill(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real_fill(*args, **kwargs)

    monkeypatch.setattr(engine, "_fill", flaky_fill)
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    assert fire(db, fake_provider) == 1
    assert (first.status, second.status) == ("open", "closed")
    assert first.stop_price == D("1200")  # tried again next tick
    assert not any(o.status == "open" for o in all_orders(db))


def test_a_partial_exit_leaves_protection_on_what_remains_and_it_closes_all_of_it(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    protect(db, fake_provider, long_reliance, "1200", None)
    engine.exit_trade(live(db, fake_provider), long_reliance.id, D("4"))
    assert long_reliance.open_quantity == D("6")
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    assert fire(db, fake_provider) == 1
    # The 4 sold at 1250 earned 4 x 1250 - 5,000 = 0; the 6 left sold at 1100 = 6,600 against 7,500.
    assert long_reliance.status == "closed"
    assert long_reliance.realized_pnl == D("-900.00")


# --- validation ---------------------------------------------------------------------------


def test_long_prices_on_the_wrong_side_are_refused_with_the_reason(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    with pytest.raises(ProtectionInvalid) as caught:
        protect(db, fake_provider, long_reliance, "1300", "1200")
    assert caught.value.code == "protection_invalid"
    assert caught.value.fields == {
        "stop_price": "For a long trade the stop-loss must be below the current price (₹1,250.00) — it's there to limit a fall.",  # noqa: E501
        "target_price": "For a long trade the target must be above the current price (₹1,250.00) — a long profits when the price rises.",  # noqa: E501
    }
    # Nothing was saved, not even the valid half.
    assert (long_reliance.stop_price, long_reliance.target_price) == (None, None)


def test_short_prices_on_the_wrong_side_are_refused_with_the_reason(
    db: Session, fake_provider: FakeProvider, zero_costs
):
    sell(db, fake_provider, "AAPL", "10")
    [trade] = all_trades(db)
    with pytest.raises(ProtectionInvalid) as caught:
        protect(db, fake_provider, trade, "220", "240")
    assert caught.value.fields == {
        "stop_price": "For a short trade the stop-loss must be above the current price ($230.00) — it's there to limit a rise.",  # noqa: E501
        "target_price": "For a short trade the target must be below the current price ($230.00) — a short profits when the price falls.",  # noqa: E501
    }
    protect(db, fake_provider, trade, "240", "220")  # the right way round is accepted
    assert (trade.stop_price, trade.target_price) == (D("240"), D("220"))


def test_a_price_equal_to_the_current_price_is_refused(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    # It would fire on the very next tick, which is an exit, not protection.
    with pytest.raises(ProtectionInvalid):
        protect(db, fake_provider, long_reliance, "1250", None)


def test_prices_must_be_positive_and_on_the_tick(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    with pytest.raises(ProtectionInvalid) as zero:
        protect(db, fake_provider, long_reliance, "0", None)
    assert "greater than zero" in zero.value.fields["stop_price"]
    with pytest.raises(ProtectionInvalid) as fine:
        protect(db, fake_provider, long_reliance, "1200.005", None)
    assert "at most 2 decimal places" in fine.value.fields["stop_price"]
    protect(db, fake_provider, long_reliance, "1200.50", None)
    assert long_reliance.stop_price == D("1200.50")


def test_crypto_allows_eight_decimal_places(db: Session, fake_provider: FakeProvider, zero_costs):
    buy(db, fake_provider, "BTC-USD", "0.1")
    [trade] = all_trades(db)
    protect(db, fake_provider, trade, "59000.12345678", None)
    assert trade.stop_price == D("59000.12345678")


def test_either_price_can_be_cleared_and_both_clears_the_expiry(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    protect(db, fake_provider, long_reliance, "1200", "1400")
    protect(db, fake_provider, long_reliance, None, "1400")
    assert (long_reliance.stop_price, long_reliance.target_price) == (None, D("1400"))
    assert long_reliance.protection_expires_at is not None
    protect(db, fake_provider, long_reliance, None, None)
    assert long_reliance.protection_expires_at is None


def test_closed_and_unknown_trades_are_refused(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    with pytest.raises(TradeNotFound):
        engine.set_protection(live(db, fake_provider), 999, D("1200"), None)
    engine.exit_trade(live(db, fake_provider), long_reliance.id)
    with pytest.raises(TradeNotOpen):
        protect(db, fake_provider, long_reliance, "1200", None)


# --- what each price leaves you with ------------------------------------------------------


def test_outcomes_equal_what_the_actual_exit_produces(
    db: Session, fake_provider: FakeProvider, fixed_clock: datetime
):
    inr_account(db)
    buy(db, fake_provider, "RELIANCE.NS", "10")  # charges 29.59, cost basis 12,529.59
    [trade] = all_trades(db)
    view = protect(db, fake_provider, trade, "1200", "1400")

    stop, target = view.stop_outcome, view.target_outcome
    assert stop is not None and target is not None
    # Stop at 1200: value 12,000.00. Brokerage 12.00, STT 12.00, NSE 0.00307% = 0.3684 -> 0.37,
    # SEBI 0.012 -> 0.01, DP 20.00, GST 18% x (12.00 + 0.37 + 0.01 + 20.00) = 18% x 32.38 = 5.8284 -> 5.83
    #   total 50.21; cash 12,000 - 50.21 = 11,949.79; realized 11,949.79 - 12,529.59 = -579.80
    assert (stop.price, stop.exit_value, stop.charges_total) == (D("1200"), D("12000.00"), D("50.21"))
    assert (stop.cash_change, stop.realized_pnl) == (D("11949.79"), D("-579.80"))
    # Target at 1400: value 14,000.00. Brokerage 14.00, STT 14.00, NSE 0.43, SEBI 0.01, DP 20.00,
    # GST 18% x (14.00 + 0.43 + 0.01 + 20.00) = 18% x 34.44 = 6.1992 -> 6.20
    #   total 54.64; cash 13,945.36; realized 13,945.36 - 12,529.59 = 1,415.77
    assert (target.exit_value, target.charges_total) == (D("14000.00"), D("54.64"))
    assert (target.cash_change, target.realized_pnl) == (D("13945.36"), D("1415.77"))

    # The same figures are what the fills then do.
    fake_provider.set_price("RELIANCE.NS", D("1200"))
    assert fire(db, fake_provider) == 1
    actual = all_orders(db)[-1]
    assert (actual.amount, actual.charges_total, actual.cash_change, actual.realized_pnl) == (
        stop.exit_value, stop.charges_total, stop.cash_change, stop.realized_pnl,
    )  # fmt: skip

    # And the target's, on its own trade.
    fake_provider.set_price("RELIANCE.NS", D("1250"))
    buy(db, fake_provider, "RELIANCE.NS", "10")
    second = all_trades(db)[-1]
    target_outcome = protect(db, fake_provider, second, None, "1400").target_outcome
    fake_provider.set_price("RELIANCE.NS", D("1400"))
    assert fire(db, fake_provider) == 1
    actual = all_orders(db)[-1]
    assert target_outcome is not None
    assert (actual.amount, actual.charges_total, actual.cash_change, actual.realized_pnl) == (
        target_outcome.exit_value, target_outcome.charges_total, target_outcome.cash_change, target_outcome.realized_pnl,  # noqa: E501
    )  # fmt: skip
    assert actual.origin == "target"


def test_outcomes_are_absent_without_a_price_and_on_closed_trades(
    db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    [view] = engine.list_trades(live(db, fake_provider))
    assert (view.stop_outcome, view.target_outcome) == (None, None)
    protect(db, fake_provider, long_reliance, "1200", None)
    [view] = engine.list_trades(live(db, fake_provider))
    assert view.stop_outcome is not None and view.target_outcome is None
    engine.exit_trade(live(db, fake_provider), long_reliance.id)
    [view] = engine.list_trades(live(db, fake_provider))
    assert (view.stop_price, view.stop_outcome) == (None, None)  # closing cleared it


# --- the API ------------------------------------------------------------------------------


def test_protection_endpoints(
    client: TestClient, db: Session, fake_provider: FakeProvider, long_reliance: Trade
):
    base = f"/api/trades/{long_reliance.id}/protection"

    preview = client.post(f"{base}/preview", json={"stop_price": "1200", "target_price": "1300"})
    assert preview.status_code == 200
    body = preview.json()
    assert (body["current_price"], body["currency"]) == ("1250", "INR")
    assert body["stop_error"] is None and body["target_error"] is None
    assert D(body["stop_outcome"]["exit_value"]) == D("12000.00")
    assert long_reliance.stop_price is None  # a preview saves nothing

    wrong = client.post(f"{base}/preview", json={"stop_price": "1300", "target_price": None})
    assert "must be below the current price" in wrong.json()["stop_error"]
    assert wrong.json()["stop_outcome"] is None

    saved = client.put(base, json={"stop_price": "1200", "target_price": "1300"})
    assert saved.status_code == 200
    out = saved.json()
    assert (out["stop_price"], out["target_price"]) == ("1200", "1300")
    assert out["stop_outcome"] == body["stop_outcome"]  # preview equals what is served
    assert out["protection_expires_at"] is not None

    refused = client.put(base, json={"stop_price": "1300", "target_price": None})
    assert refused.status_code == 400
    assert refused.json()["code"] == "protection_invalid"
    assert "stop-loss must be below" in refused.json()["detail"]
    assert set(refused.json()["fields"]) == {"stop_price"}

    junk = client.put(base, json={"stop_price": "abc"})
    assert junk.status_code == 422
    assert "Stop-loss must be a price" in junk.json()["detail"]

    cleared = client.put(base, json={"stop_price": None, "target_price": None})
    assert (cleared.json()["stop_price"], cleared.json()["stop_outcome"]) == (None, None)

    assert client.put("/api/trades/999/protection", json={}).json()["code"] == "trade_not_found"
    listed = client.get("/api/trades").json()
    assert listed[0]["stop_price"] is None


def test_the_background_loop_runs_it_before_square_off():
    from app.trading.tick import TICK_STEPS

    names = [name for name, _ in TICK_STEPS]
    assert names.index("Firing stop-losses and targets") < names.index("Squaring off intraday shorts")


def test_protection_never_uses_the_wall_clock(db: Session, fake_provider: FakeProvider, long_reliance: Trade):
    # The fixed clock is 2026-03-02; a wall-clock expiry would be a year from today's real date.
    protect(db, fake_provider, long_reliance, "1200", None)
    assert long_reliance.protection_expires_at == datetime(2027, 3, 2, 10, 30, tzinfo=UTC)
