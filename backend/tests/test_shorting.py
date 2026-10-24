"""Trades and short selling, through the engine and the API.

Fake prices: RELIANCE.NS 1250 INR, AAPL 230 USD, SAP.DE 200 EUR (no short rule), BTC-USD 60000.
Default brokers: Groww (India), Interactive Brokers (international), CoinDCX (crypto). Tests that
are about trades rather than charges use `zero_costs`. Every expected figure is worked out beside
the assertion; if one disagrees with the code, recompute it before touching the engine.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.market_data.fake import FakeProvider
from app.models import Order, OrderSide, OrderStatus, OrderType, Trade
from app.schemas import OrderLegOut
from app.trading import engine
from app.trading.engine import live_context as live
from app.trading.errors import (
    InsufficientFunds,
    ShortMarketClosed,
    ShortNotOffered,
    ShortQuantityInvalid,
    TradeNotFound,
    TradeNotOpen,
)

D = Decimal
real_calendar = pytest.mark.real_calendar


def place(db: Session, provider: FakeProvider, side: str, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=side, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def buy(db, provider, symbol, qty, **kw) -> Order:
    return place(db, provider, OrderSide.BUY, symbol, qty, **kw)


def sell(db, provider, symbol, qty, **kw) -> Order:
    return place(db, provider, OrderSide.SELL, symbol, qty, **kw)


def inr_account(db: Session, cash: str = "1000000") -> None:
    account = engine.get_account(db)
    account.currency = "INR"
    account.cash = account.starting_cash = D(cash)
    db.commit()


def lines(order: Order) -> dict[str, str]:
    return {c["name"]: c["amount"] for c in order.charges}


def trades(db: Session, symbol: str | None = None) -> list[Trade]:
    query = select(Trade).order_by(Trade.id)
    if symbol:
        query = query.where(Trade.symbol == symbol)
    return list(db.scalars(query))


def at(monkeypatch: pytest.MonkeyPatch, *args: int) -> datetime:
    when = datetime(*args, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: when)
    return when


def assert_books_balance(db: Session, provider: FakeProvider) -> None:
    pf = engine.get_portfolio(live(db, provider))
    assert pf.realized_pnl + pf.unrealized_pnl == pf.total_pnl
    assert pf.total_pnl == pf.total_value - pf.starting_cash
    assert pf.available_cash == pf.cash - pf.margin_used
    assert pf.available_cash >= 0


# --- the anchor: shorting 10 RELIANCE.NS at 1250 -------------------------------------------


def test_short_10_reliance_costs_18_34_intraday_and_blocks_2500(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    order = sell(db, fake_provider, "RELIANCE.NS", "10")
    # value 10 x 1250 = 12500.00, Groww, intraday, sell side:
    #   brokerage 0.1% = 12.50 (min 5, cap 20)    STT 0.025% = 3.125 -> 3.13 (sell side only)
    #   stamp duty: buy side only, none here      NSE 0.00307% = 0.38375 -> 0.38
    #   SEBI 0.0001% = 0.0125 -> 0.01             DP: none, intraday never touches the demat account
    #   GST 18% x (12.50 + 0.38 + 0.01) = 18% x 12.89 = 2.3202 -> 2.32
    #   total 12.50 + 3.13 + 0.38 + 0.01 + 2.32 = 18.34
    assert order.status == OrderStatus.FILLED
    assert lines(order) == {
        "Brokerage": "12.50",
        "Securities transaction tax (STT)": "3.13",
        "Exchange transaction charge": "0.38",
        "SEBI turnover fee": "0.01",
        "GST": "2.32",
    }
    assert order.charges_total == D("18.34")
    # The proceeds are not paid out; only the charges leave cash, and 20% x 12500 = 2500 is blocked.
    assert order.cash_change == D("-18.34")
    account = engine.get_account(db)
    assert account.cash == D("999981.66")
    assert account.margin_used == D("2500.00")
    [trade] = trades(db)
    assert (trade.direction, trade.product, trade.status) == ("short", "intraday", "open")
    assert (trade.entry_value, trade.entry_charges, trade.margin_blocked) == (
        D("12500.00"), D("18.34"), D("2500.00"),
    )  # fmt: skip
    assert order.trade_id == trade.id and trade.opened_by_order_id == order.id
    assert_books_balance(db, fake_provider)


def test_short_round_trip_at_an_unchanged_price_loses_exactly_the_charges_at_both_ends(
    db: Session, fake_provider: FakeProvider, fixed_clock: datetime
):
    inr_account(db)
    short = sell(db, fake_provider, "RELIANCE.NS", "10")
    cover = buy(db, fake_provider, "RELIANCE.NS", "10")
    # Cover (intraday buy) at 1250: brokerage 12.50, stamp 0.003% = 0.375 -> 0.38, NSE 0.38,
    # SEBI 0.01, GST 18% x (12.50 + 0.38 + 0.01) = 2.3202 -> 2.32; STT is sell side only.
    # total 12.50 + 0.38 + 0.38 + 0.01 + 2.32 = 15.59
    assert cover.charges_total == D("15.59")
    # lost 18.34 + 15.59 = 33.93; the cover returns (12500 - 12500) - 15.59 to cash
    assert cover.cash_change == D("-15.59")
    assert cover.realized_pnl == D("-33.93")
    account = engine.get_account(db)
    assert account.cash == D("999966.07")  # 1,000,000 - 33.93
    assert account.realized_pnl == D("-33.93")
    assert account.margin_used == D("0")
    [trade] = trades(db)
    assert (trade.status, trade.closed_how, trade.closed_at) == ("closed", "cover", fixed_clock)
    assert (trade.open_quantity, trade.entry_charges, trade.margin_blocked) == (D("0"), D("0"), D("0"))
    assert trade.realized_pnl == D("-33.93")
    assert short.charges_total + cover.charges_total == D("33.93")

    # The trade is closed and its remaining entry charges are gone, but it still reports what
    # getting in cost, from the order that opened it.
    [view] = engine.list_trades(live(db, fake_provider), status="closed")
    assert view.entry_charges_paid == D("18.34")
    assert view.exit_charges == D("15.59")
    assert_books_balance(db, fake_provider)


def test_open_short_losses_and_the_identity_hold_to_the_paisa(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    sell(db, fake_provider, "RELIANCE.NS", "10")
    fake_provider.set_price("RELIANCE.NS", D("1300"))
    pf = engine.get_portfolio(live(db, fake_provider))
    # Covering would cost 10 x 1300 = 13000 against 12500 taken in: short value 12500 - 13000 = -500.
    # unrealized = -500 - 18.34 entry charges = -518.34; nothing realized yet.
    # total value = 999,981.66 cash - 500 = 999,481.66; total P&L = -518.34
    assert pf.short_value == D("-500.00")
    assert pf.unrealized_pnl == D("-518.34")
    assert pf.realized_pnl == D("0")
    assert pf.total_value == D("999481.66")
    assert pf.total_pnl == D("-518.34")
    assert (pf.margin_used, pf.available_cash) == (D("2500.00"), D("997481.66"))
    [holding] = pf.holdings
    assert (holding.direction, holding.quantity, holding.avg_price) == ("short", D("10"), D("1250"))
    assert holding.market_value == D("13000.00")
    assert holding.break_even_price is not None and holding.break_even_price < D("1250")
    assert_books_balance(db, fake_provider)

    # A partial cover, then a long elsewhere, then another move: still exact.
    buy(db, fake_provider, "RELIANCE.NS", "4")
    buy(db, fake_provider, "AAPL", "3")
    fake_provider.set_price("RELIANCE.NS", D("1180"))
    fake_provider.set_price("AAPL", D("251.37"))
    assert_books_balance(db, fake_provider)


# --- one order, two legs -------------------------------------------------------------------


def test_selling_8_holding_5_closes_5_and_shorts_3_each_under_its_own_product(
    db: Session, fake_provider: FakeProvider
):
    inr_account(db)
    bought = buy(db, fake_provider, "RELIANCE.NS", "5")
    # Buy 5 x 1250 = 6250 delivery: brokerage 6.25, STT 0.1% = 6.25, stamp 0.015% = 0.9375 -> 0.94,
    # NSE 0.191875 -> 0.19, SEBI 0.00625 -> 0.01, GST 18% x (6.25 + 0.19 + 0.01) = 1.161 -> 1.16
    # total 14.80; the trade's cost basis is 6250 + 14.80 = 6264.80.
    assert bought.charges_total == D("14.80")

    order = sell(db, fake_provider, "RELIANCE.NS", "8")
    close_leg, short_leg = order.legs
    assert (close_leg["kind"], close_leg["quantity"], close_leg["product"]) == ("close_long", "5", "delivery")
    assert (short_leg["kind"], short_leg["quantity"], short_leg["product"]) == ("open_short", "3", "intraday")
    # close 5, delivery: brokerage 6.25, STT 6.25, NSE 0.19, SEBI 0.01, DP 20.00,
    #   GST 18% x (6.25 + 0.19 + 0.01 + 20.00) = 18% x 26.45 = 4.761 -> 4.76 => 37.46
    assert close_leg["charges_total"] == "37.46"
    # short 3, intraday: value 3750; brokerage 0.1% = 3.75 lifted to the Rs 5 minimum, STT 0.025% =
    #   0.9375 -> 0.94, NSE 0.115125 -> 0.12, SEBI 0.00375 -> nothing,
    #   GST 18% x (5.00 + 0.12) = 0.9216 -> 0.92 => 6.98, and no DP charge
    assert short_leg["charges_total"] == "6.98"
    assert order.charges_total == D("44.44")
    assert lines(order)["Brokerage"] == "11.25"  # 6.25 + 5.00, merged for the order
    assert "Depository (DP) charge" in lines(order)
    # realized on the closing leg: 6250 - 37.46 - 6264.80 = -52.26
    assert close_leg["realized_pnl"] == "-52.26" and order.realized_pnl == D("-52.26")
    # cash: -6264.80 for the buy, then (6250 - 37.46) - 6.98 = +6205.56 -> 999,940.76
    assert order.cash_change == D("6205.56")
    account = engine.get_account(db)
    assert account.cash == D("999940.76")
    assert account.margin_used == D("750.00")  # 20% x 3750
    long_trade, short_trade = trades(db)
    assert (long_trade.status, long_trade.closed_how) == ("closed", "sell")
    assert (short_trade.direction, short_trade.open_quantity, short_trade.margin_blocked) == (
        "short", D("3"), D("750.00"),
    )  # fmt: skip
    assert close_leg["trade_id"] == long_trade.id and short_leg["trade_id"] == short_trade.id
    assert_books_balance(db, fake_provider)


def test_preview_and_fill_agree_for_a_two_leg_order(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    buy(db, fake_provider, "RELIANCE.NS", "5")
    cash_before = engine.get_account(db).cash
    preview = engine.preview_order(
        live(db, fake_provider), symbol="RELIANCE.NS", side="sell", type="market", quantity=D("8")
    )
    order = sell(db, fake_provider, "RELIANCE.NS", "8")
    # The short leg has no trade id in a preview, so legs are compared field by field.
    for pl, ol in zip(preview.legs, order.legs, strict=True):
        assert (pl.kind, str(pl.quantity), pl.product) == (ol["kind"], ol["quantity"], ol["product"])
        assert f"{pl.charges_total:f}" == ol["charges_total"]
        assert f"{pl.cash_change:f}" == ol["cash_change"]
    assert preview.charges_total == order.charges_total
    assert preview.cash_change == order.cash_change == engine.get_account(db).cash - cash_before
    assert preview.margin_change == D("750.00")
    assert preview.realized_pnl == order.realized_pnl


def test_a_buy_covers_shorts_first_and_only_the_rest_opens_a_long(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    sell(db, fake_provider, "RELIANCE.NS", "10")
    order = buy(db, fake_provider, "RELIANCE.NS", "15")
    cover, long = order.legs
    assert (cover["kind"], cover["quantity"], cover["product"]) == ("close_short", "10", "intraday")
    assert (long["kind"], long["quantity"], long["product"]) == ("open_long", "5", "delivery")
    assert engine.get_account(db).margin_used == D("0")
    short_trade, long_trade = trades(db)
    assert short_trade.status == "closed" and short_trade.closed_how == "cover"
    assert (long_trade.direction, long_trade.open_quantity) == ("long", D("5"))
    assert_books_balance(db, fake_provider)


def test_a_sell_closes_the_oldest_longs_first(db: Session, fake_provider: FakeProvider, zero_costs):
    fake_provider.set_price("AAPL", D("100"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("110"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("120"))
    order = sell(db, fake_provider, "AAPL", "15")
    first, second = trades(db)
    # 10 of the lot bought at 100 (realized 10 x 20 = 200) and 5 of the one at 110 (5 x 10 = 50)
    assert [(leg["trade_id"], leg["quantity"]) for leg in order.legs] == [(first.id, "10"), (second.id, "5")]
    assert order.realized_pnl == D("250.00")
    assert first.status == "closed" and second.open_quantity == D("5")
    assert second.cost_basis == D("550.00")


# --- exits ---------------------------------------------------------------------------------


def test_fifo_exit_in_india_closes_the_oldest_lot_whichever_trade_was_named(
    db: Session, fake_provider: FakeProvider, zero_costs
):
    inr_account(db)
    fake_provider.set_price("RELIANCE.NS", D("1000"))
    buy(db, fake_provider, "RELIANCE.NS", "3")
    fake_provider.set_price("RELIANCE.NS", D("1100"))
    buy(db, fake_provider, "RELIANCE.NS", "2")
    first, second = trades(db)
    fake_provider.set_price("RELIANCE.NS", D("1200"))

    preview = engine.preview_exit(live(db, fake_provider), second.id)
    assert preview.fifo is True and "FIFO" in preview.note and "NSE" in preview.note
    # Asked to exit trade 2 (2 shares): India pools holdings, so the oldest 2 of trade 1 close.
    # realized 2 x 1200 - 2 x 1000 = 400
    assert [(leg.trade_id, leg.quantity) for leg in preview.legs] == [(first.id, D("2"))]
    assert preview.realized_pnl == D("400.00")

    order = engine.exit_trade(live(db, fake_provider), second.id)
    db.refresh(first)
    db.refresh(second)
    assert (first.open_quantity, second.open_quantity) == (D("1"), D("2"))
    assert order.realized_pnl == D("400.00") and order.trade_id == second.id
    assert [leg["trade_id"] for leg in order.legs] == [first.id]
    assert_books_balance(db, fake_provider)


def test_specific_lot_exit_in_the_us_closes_exactly_the_named_trade(
    db: Session, fake_provider: FakeProvider, zero_costs
):
    fake_provider.set_price("AAPL", D("100"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("110"))
    buy(db, fake_provider, "AAPL", "10")
    first, second = trades(db)
    fake_provider.set_price("AAPL", D("120"))
    preview = engine.preview_exit(live(db, fake_provider), second.id)
    assert preview.fifo is False and preview.note == ""
    order = engine.exit_trade(live(db, fake_provider), second.id)
    db.refresh(first)
    db.refresh(second)
    # 10 x 120 = 1200 against the 1100 that lot cost: realized 100. The older lot is untouched.
    assert order.realized_pnl == D("100.00")
    assert (second.status, second.closed_how) == ("closed", "exit")
    assert first.status == "open" and first.open_quantity == D("10")
    # A partial exit of the other lot: 4 x 120 = 480 against 1000 x 4/10 = 400.
    engine.exit_trade(live(db, fake_provider), first.id, D("4"))
    db.refresh(first)
    assert (first.open_quantity, first.cost_basis, first.realized_pnl) == (D("6"), D("600.00"), D("80.00"))


def test_exiting_a_short_trade_and_a_trade_that_is_gone(db: Session, fake_provider: FakeProvider, zero_costs):
    sell(db, fake_provider, "AAPL", "10")
    [short] = trades(db)
    fake_provider.set_price("AAPL", D("200"))
    order = engine.exit_trade(live(db, fake_provider), short.id)
    # sold at 230, bought back at 200: 10 x 30 = 300
    assert (order.side, order.realized_pnl, order.origin) == ("buy", D("300.00"), "exit")
    with pytest.raises(TradeNotOpen):
        engine.exit_trade(live(db, fake_provider), short.id)
    with pytest.raises(TradeNotFound):
        engine.preview_exit(live(db, fake_provider), 999)


def test_partial_exit_allocates_entry_charges_pro_rata_and_the_order_keeps_them(
    db: Session, fake_provider: FakeProvider
):
    inr_account(db)
    buy(db, fake_provider, "RELIANCE.NS", "10")  # charges 29.59, cost basis 12529.59
    [trade] = trades(db)
    first_exit = engine.exit_trade(live(db, fake_provider), trade.id, D("4"))
    # Exit 4 x 1250 = 5000: brokerage 5.00, STT 5.00, NSE 0.1535 -> 0.15, SEBI 0.005 -> 0.01,
    # DP 20.00, GST 18% x (5.00 + 0.15 + 0.01 + 20.00) = 4.5288 -> 4.53 => 34.69
    # cost out 12529.59 x 4/10 = 5011.836 -> 5011.84, of which entry charges 29.59 x 4/10 = 11.836 -> 11.84
    # realized 5000 - 34.69 - 5011.84 = -46.53
    assert first_exit.charges_total == D("34.69")
    assert first_exit.realized_pnl == D("-46.53")
    leg = first_exit.legs[0]
    assert leg["entry_charges"] == "11.84"  # immutable record of what was released
    db.refresh(trade)
    # left: 6 shares, cost 12529.59 - 5011.84 = 7517.75, entry charges 29.59 - 11.84 = 17.75, value 7500.00
    assert (trade.open_quantity, trade.cost_basis, trade.entry_charges, trade.entry_value) == (
        D("6"), D("7517.75"), D("17.75"), D("7500.00"),
    )  # fmt: skip
    engine.exit_trade(live(db, fake_provider), trade.id)
    db.refresh(trade)
    assert (trade.status, trade.cost_basis, trade.entry_charges) == ("closed", D("0.00"), D("0.00"))
    [view] = engine.list_trades(live(db, fake_provider), status="closed")
    assert view.entry_charges_paid == D("29.59")  # not zero, though the trade has fully closed
    assert_books_balance(db, fake_provider)


# --- the rules that refuse a short ---------------------------------------------------------


def test_germany_refuses_a_short_with_a_readable_sentence(db: Session, fake_provider: FakeProvider):
    with pytest.raises(ShortNotOffered) as exc:
        sell(db, fake_provider, "SAP.DE", "1")
    assert exc.value.message == "Short selling isn't offered on Germany (Xetra) for retail accounts."
    with pytest.raises(ShortNotOffered):
        engine.preview_order(
            live(db, fake_provider), symbol="SAP.DE", side="sell", type="market", quantity=D(1)
        )
    assert db.scalars(select(Order)).all() == [] and trades(db) == []


def test_us_shorts_are_whole_shares_but_a_fractional_long_can_still_be_sold(
    db: Session, fake_provider: FakeProvider, zero_costs
):
    with pytest.raises(ShortQuantityInvalid) as exc:
        sell(db, fake_provider, "AAPL", "2.5")
    assert exc.value.message == "You can only short whole US shares — nobody lends a fraction of a share."

    buy(db, fake_provider, "AAPL", "2.5")
    # Selling the whole fractional long is a close, not a short, so the whole-share rule is silent.
    assert sell(db, fake_provider, "AAPL", "2.5").status == OrderStatus.FILLED
    buy(db, fake_provider, "AAPL", "2.5")
    # 3.5 against 2.5 held: close 2.5 and short 1 whole share: allowed
    order = sell(db, fake_provider, "AAPL", "3.5")
    legs = [(leg["kind"], leg["quantity"]) for leg in order.legs]
    assert legs == [("close_long", "2.5"), ("open_short", "1")]
    # 3.3 against nothing held shorts 3.3: refused; the rule looks at the short part only
    with pytest.raises(ShortQuantityInvalid):
        sell(db, fake_provider, "AAPL", "3.3")
    # and 1.3 against the 1 still short is a pure short of 1.3
    with pytest.raises(ShortQuantityInvalid):
        sell(db, fake_provider, "AAPL", "1.3")


@real_calendar
def test_an_indian_intraday_short_cannot_be_placed_while_the_market_is_closed(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    inr_account(db)
    # Saturday 2026-03-07 11:30 IST (06:00 UTC): NSE is shut for the weekend.
    at(monkeypatch, 2026, 3, 7, 6, 0)
    with pytest.raises(ShortMarketClosed) as exc:
        sell(db, fake_provider, "RELIANCE.NS", "10")
    assert "after-market order" in exc.value.message and "IST" in exc.value.message
    assert db.scalars(select(Order)).all() == []
    # A buy can still wait for the open, and a US short (held overnight) is not an intraday product.
    assert buy(db, fake_provider, "RELIANCE.NS", "1").status == OrderStatus.OPEN


def test_available_cash_can_never_go_negative(db: Session, fake_provider: FakeProvider):
    inr_account(db, "3000")
    sell(db, fake_provider, "RELIANCE.NS", "10")  # charges 18.34 + margin 2500.00 = 2518.34 of 3000
    account = engine.get_account(db)
    assert (account.cash, account.margin_used) == (D("2981.66"), D("2500.00"))
    before = (account.cash, account.margin_used, len(trades(db)))
    with pytest.raises(InsufficientFunds) as exc:
        sell(db, fake_provider, "RELIANCE.NS", "10")
    # available 2981.66 - 2500.00 = 481.66, but a second short needs 18.34 + 2500.00 = 2518.34
    assert "2,518.34" in exc.value.message and "481.66" in exc.value.message
    assert "held as margin" in exc.value.message
    with pytest.raises(InsufficientFunds):
        buy(db, fake_provider, "TCS.NS", "1")  # 4100 + charges needs more than 481.66
    # (a buy of RELIANCE would not be refused: it covers the short first, which releases margin)
    account = engine.get_account(db)
    assert (account.cash, account.margin_used, len(trades(db))) == before
    assert account.cash - account.margin_used >= 0


# --- borrow and funding --------------------------------------------------------------------


def test_us_borrow_accrues_daily_on_the_entry_value(
    db: Session,
    fake_provider: FakeProvider,
    fixed_clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
    zero_costs,
):
    sell(db, fake_provider, "AAPL", "10")
    [trade] = trades(db)
    # value 10 x 230 = 2300; Reg T margin 50% = 1150; cash untouched (no charges, proceeds held back)
    assert (engine.get_account(db).margin_used, trade.financing_accrued_until) == (D("1150.00"), fixed_clock)
    assert engine.accrue_financing(live(db, fake_provider)) == 0  # no day has completed

    at(monkeypatch, 2026, 3, 2, 10, 29)  # one minute short of a day
    assert engine.accrue_financing(live(db, fake_provider)) == 0

    later = fixed_clock + timedelta(days=30, hours=5)
    monkeypatch.setattr(clock, "now", lambda: later)
    assert engine.accrue_financing(live(db, fake_provider)) == 1
    # 30 whole days at 3% a year on 2300: 2300 x 3% x 30 / 365 = 2070 / 365 = 5.6712 -> 5.67
    db.refresh(trade)
    account = engine.get_account(db)
    assert trade.financing_paid == D("5.67")
    assert trade.financing_accrued_until == fixed_clock + timedelta(days=30)  # the 5 hours carry over
    assert account.cash == D("99994.33")
    assert account.realized_pnl == D("-5.67") and trade.realized_pnl == D("-5.67")
    assert engine.accrue_financing(live(db, fake_provider)) == 0  # nothing new until the next day completes

    fake_provider.set_price("AAPL", D("241.50"))
    assert_books_balance(db, fake_provider)  # realized + unrealized == total P&L, financing included
    pf = engine.get_portfolio(live(db, fake_provider))
    assert pf.financing_paid == D("5.67")
    # short value 2300 - 2415 = -115; total value 99994.33 - 115 = 99879.33; total P&L -120.67
    assert pf.total_pnl == D("-120.67")
    assert pf.realized_pnl == D("-5.67") and pf.unrealized_pnl == D("-115.00")


def test_crypto_funding_is_charged_per_completed_eight_hour_period(
    db: Session,
    fake_provider: FakeProvider,
    fixed_clock: datetime,
    monkeypatch: pytest.MonkeyPatch,
    zero_costs,
):
    sell(db, fake_provider, "BTC-USD", "0.1")
    [trade] = trades(db)
    # 0.1 x 60000 = 6000; margin 20% = 1200; product margin
    assert (trade.product, trade.margin_blocked) == ("margin", D("1200.00"))
    monkeypatch.setattr(clock, "now", lambda: fixed_clock + timedelta(hours=7, minutes=59))
    assert engine.accrue_financing(live(db, fake_provider)) == 0
    monkeypatch.setattr(clock, "now", lambda: fixed_clock + timedelta(hours=20))
    assert engine.accrue_financing(live(db, fake_provider)) == 1
    # two completed periods (16 h) at 0.01% of 6000 = 0.60 each = 1.20; the other 4 h wait
    db.refresh(trade)
    assert trade.financing_paid == D("1.20")
    assert trade.financing_accrued_until == fixed_clock + timedelta(hours=16)
    assert engine.get_account(db).cash == D("99998.80")
    assert_books_balance(db, fake_provider)


# --- the square-off ------------------------------------------------------------------------


@real_calendar
def test_square_off_runs_at_15_20_ist(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    inr_account(db)
    # Monday 2026-03-02 10:30 IST (05:00 UTC): NSE open since 09:15 IST, closing at 15:30 IST.
    at(monkeypatch, 2026, 3, 2, 5, 0)
    sell(db, fake_provider, "RELIANCE.NS", "10")
    assert engine.square_off_due(live(db, fake_provider)) == []

    at(monkeypatch, 2026, 3, 2, 9, 49)  # 15:19 IST: a minute early
    assert engine.square_off_due(live(db, fake_provider)) == []

    at(monkeypatch, 2026, 3, 2, 9, 50)  # 15:20 IST: ten minutes before the 15:30 close
    [order] = engine.square_off_due(live(db, fake_provider))
    assert (order.origin, order.side, order.quantity) == ("square_off", "buy", D("10"))
    assert order.status == "filled"
    assert order.note == "Squared off at 15:20 IST."
    [trade] = trades(db)
    assert (trade.status, trade.closed_how) == ("closed", "square_off")
    assert order.trade_id == trade.id
    assert engine.get_account(db).margin_used == D("0")
    assert engine.square_off_due(live(db, fake_provider)) == []  # nothing left to do
    assert_books_balance(db, fake_provider)


@real_calendar
def test_a_short_left_from_yesterday_is_squared_off_at_the_first_fresh_quote(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    inr_account(db)
    at(monkeypatch, 2026, 3, 9, 5, 0)  # Monday 10:30 IST
    sell(db, fake_provider, "RELIANCE.NS", "10")
    # Tuesday 2026-03-10 09:14 IST (03:44 UTC): shut until 09:15, so nothing happens yet.
    at(monkeypatch, 2026, 3, 10, 3, 44)
    assert engine.square_off_due(live(db, fake_provider)) == []
    # 09:15 IST (03:45 UTC): open, and the fake stamps its quote with the clock: out at once.
    at(monkeypatch, 2026, 3, 10, 3, 45)
    [order] = engine.square_off_due(live(db, fake_provider))
    assert order.note == "Squared off at 09:15 IST, left open from an earlier session."
    assert trades(db)[0].closed_how == "square_off"

    # A stale quote (still yesterday's close) does not count as a fresh one.
    inr_account(db)
    engine.reset_account(live(db, FakeProvider()))
    at(monkeypatch, 2026, 3, 9, 5, 0)
    sell(db, fake_provider, "RELIANCE.NS", "10")
    at(monkeypatch, 2026, 3, 10, 3, 45)
    fake_provider.set_as_of("RELIANCE.NS", int(datetime(2026, 3, 9, 10, 0, tzinfo=UTC).timestamp()))
    assert engine.square_off_due(live(db, fake_provider)) == []


# --- the API -------------------------------------------------------------------------------


def test_legs_survive_the_api_boundary_and_match_their_model(client: TestClient):
    placed = client.post("/api/orders", json={"symbol": "AAPL", "side": "sell", "quantity": "5"})
    assert placed.status_code == 200, placed.text
    body = placed.json()
    # Nothing held: the whole sell is a short, charged as a margin product at IBKR.
    [leg] = body["legs"]
    assert (leg["kind"], leg["product"], leg["quantity"]) == ("open_short", "margin", "5")
    assert OrderLegOut.model_validate(leg).model_dump(mode="json") == leg  # what is stored is what is served
    assert body["origin"] == "user" and body["trade_id"] == leg["trade_id"]
    assert body["cash_change"] == f"-{body['charges_total']}"

    listed = client.get("/api/orders").json()
    assert listed[0]["legs"] == body["legs"]

    portfolio = client.get("/api/portfolio").json()
    assert portfolio["margin_used"] == "575.00"  # 50% x 5 x 230
    assert portfolio["holdings"][0]["direction"] == "short"
    assert D(portfolio["available_cash"]) == D(portfolio["cash"]) - D("575.00")
    [trade] = portfolio["trades"]
    assert trade["id"] == leg["trade_id"] and trade["lot_exits"] == "specific"

    trade_list = client.get("/api/trades", params={"status": "open", "symbol": "aapl"}).json()
    assert [t["id"] for t in trade_list] == [trade["id"]]
    assert client.get("/api/trades", params={"status": "closed"}).json() == []

    preview = client.post(f"/api/trades/{trade['id']}/exit/preview", json={"quantity": "2"})
    assert preview.status_code == 200, preview.text
    pbody = preview.json()
    assert pbody["fifo"] is False and pbody["legs"][0]["kind"] == "close_short"
    assert pbody["legs"][0]["trade_id"] == trade["id"]

    exited = client.post(f"/api/trades/{trade['id']}/exit", json={"quantity": "2"})
    assert exited.status_code == 200, exited.text
    assert exited.json()["legs"][0]["quantity"] == "2"
    assert exited.json()["trade_id"] == trade["id"]
    rest = client.post(f"/api/trades/{trade['id']}/exit")  # no body: the whole open part
    assert rest.status_code == 200 and rest.json()["legs"][0]["quantity"] == "3"
    again = client.post(f"/api/trades/{trade['id']}/exit")
    assert again.status_code == 400 and "already closed" in again.json()["detail"]
    [closed] = client.get("/api/trades", params={"status": "closed"}).json()
    assert D(closed["entry_charges_paid"]) > 0 and closed["closed_how"] == "exit"
    assert client.get("/api/trades", params={"status": "bogus"}).status_code == 422
    bad = client.post(f"/api/trades/{trade['id']}/exit", json={"quantity": 2})
    assert bad.status_code == 422 and isinstance(bad.json()["detail"], str)


def test_preview_in_germany_is_a_400_with_the_sentence(client: TestClient):
    response = client.post("/api/orders/preview", json={"symbol": "SAP.DE", "side": "sell", "quantity": "1"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Short selling isn't offered on Germany (Xetra) for retail accounts."


def test_market_status_says_how_shorting_works(client: TestClient):
    us = client.get("/api/market/quote", params={"symbol": "AAPL"}).json()["market"]
    assert us["lot_exits"] == "specific"
    assert us["short_selling"] == {
        "style": "overnight", "margin_percent": "50", "borrow_percent_year": "3",
        "square_off_minutes_before_close": None, "min_shortable_step": "1",
    }  # fmt: skip
    de = client.get("/api/market/quote", params={"symbol": "SAP.DE"}).json()["market"]
    assert de["short_selling"] is None and de["lot_exits"] == "fifo"


def test_converting_the_account_currency_moves_margin_trades_and_legs_together(
    db: Session, fake_provider: FakeProvider, zero_costs
):
    sell(db, fake_provider, "AAPL", "10")  # value 2300, margin 1150
    assert engine.convert_account_currency(live(db, fake_provider), "INR") is True
    db.expire_all()
    account = engine.get_account(db)
    # 1150 x 83.5 = 96025.00
    assert account.margin_used == D("96025.00")
    [trade] = trades(db)
    assert (trade.margin_blocked, trade.entry_value) == (D("96025.00"), D("192050.00"))
    assert trade.cost_basis == trade.entry_value + trade.entry_charges
    [order] = db.scalars(select(Order))
    assert order.legs[0]["margin_change"] == "96025.00"
    assert OrderLegOut.model_validate(order.legs[0]).model_dump(mode="json") == order.legs[0]
