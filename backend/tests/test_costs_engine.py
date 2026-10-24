"""Charges through the engine: real fee schedules, no zero_costs.

Fake prices: AAPL 230 USD, RELIANCE.NS 1250 INR, BTC-USD 60000, VOD.L 0.72 GBP,
INRUSD=X 0.011976. Default brokers: Groww (India), Interactive Brokers (international),
CoinDCX (crypto). Worked figures sit beside each assertion.
"""

from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.base import Instrument
from app.market_data.fake import FakeProvider
from app.models import Order, OrderSide, OrderStatus, OrderType, Trade
from app.schemas import ChargeOut
from app.trading import brokers, engine
from app.trading.errors import BrokerNotAvailable, InsufficientFunds, InvalidBroker, UnsupportedMarket
from app.trading.fees import Fee
from tests.helpers import live

D = Decimal


def place(db: Session, provider: FakeProvider, side: str, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=side, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def inr_account(db: Session) -> None:
    """Make the account a rupee account with 10 lakh, as step 12 will."""
    account = engine.get_account(db)
    account.currency = "INR"
    account.cash = account.starting_cash = D("1000000")
    db.commit()


def lines(order: Order) -> dict[str, str]:
    return {c["name"]: c["amount"] for c in order.charges}


def test_groww_anchor_through_the_engine(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    order = place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    # 10 x 1250 = 12500; charges 29.59 (see test_fees); cash 1,000,000 - 12,500 - 29.59 = 987,470.41
    assert order.amount == D("12500.00")
    assert order.charges_total == D("29.59")
    assert lines(order) == {
        "Brokerage": "12.50",
        "Exchange transaction charge": "0.38",
        "Securities transaction tax (STT)": "12.50",
        "Stamp duty": "1.88",
        "SEBI turnover fee": "0.01",
        "GST": "2.32",
    }
    assert engine.get_account(db).cash == D("987470.41")
    # The position carries everything paid: 12500 + 29.59
    trade = db.scalar(select(Trade))
    assert (trade.entry_price, trade.cost_basis) == (D("1250"), D("12529.59"))
    assert (trade.entry_value, trade.entry_charges) == (D("12500.00"), D("29.59"))


def test_round_trip_at_an_unchanged_price_loses_exactly_the_charges_inr(
    db: Session, fake_provider: FakeProvider
):
    inr_account(db)
    buy = place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    sell = place(db, fake_provider, OrderSide.SELL, "RELIANCE.NS", "10")
    # sell charges: brokerage 12.50, STT 12.50, exchange 0.38, SEBI 0.01, DP 20.00,
    #   GST 18% x (12.50 + 0.38 + 0.01 + 20.00) = 18% x 32.89 = 5.9202 = 5.92 -> 51.31
    assert sell.charges_total == D("51.31")
    # lost = 29.59 + 51.31 = 80.90; cash 1,000,000 - 80.90 = 999,919.10
    # realized = (12500 - 51.31) - 12529.59 = -80.90
    assert sell.realized_pnl == D("-80.90")
    account = engine.get_account(db)
    assert account.cash == D("999919.10")
    assert account.cash == account.starting_cash - buy.charges_total - sell.charges_total
    assert account.realized_pnl == D("-80.90")
    assert db.scalars(select(Trade).where(Trade.status == "open")).all() == []


def test_round_trip_at_an_unchanged_price_loses_exactly_the_charges_usd(
    db: Session, fake_provider: FakeProvider
):
    buy = place(db, fake_provider, OrderSide.BUY, "AAPL", "10")
    sell = place(db, fake_provider, OrderSide.SELL, "AAPL", "10")
    # IBKR US: 10 x 0.005 = 0.05, lifted to the $1 minimum (1% of 2300 = 23 is no cap) -> 1.00
    # (the $0.00003 CAT fee rounds to nothing). Buy charges 1.00.
    # Sell: brokerage 1.00 + SEC fee 0.00206% x 2300 = 0.04738 = 0.05 -> 1.05.
    assert buy.charges_total == D("1.00")
    assert sell.charges_total == D("1.05")
    # cash 100000 - 2300 - 1.00 + 2300 - 1.05 = 99997.95, i.e. exactly 2.05 lost
    account = engine.get_account(db)
    assert account.cash == D("99997.95")
    assert sell.realized_pnl == D("-2.05")
    assert account.cash - account.starting_cash == account.realized_pnl


def test_foreign_instrument_charges_are_converted_at_the_end(db: Session, fake_provider: FakeProvider):
    # USD account, Groww, RELIANCE.NS: charges are worked out in INR (29.59 total) and each is
    # converted at 0.011976 and rounded on its own:
    #   brokerage 12.50 -> 0.1497 = 0.15      STT 12.50 -> 0.15
    #   stamp 1.88 -> 0.02251 = 0.02          exchange 0.38 -> 0.00455 = 0.00
    #   SEBI 0.01 -> 0.00012 = 0.00           GST 2.32 -> 0.02778 = 0.03
    # total 0.15 + 0.15 + 0.02 + 0.00 + 0.00 + 0.03 = 0.35; value 12500 x 0.011976 = 149.70
    order = place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    assert lines(order) == {
        "Brokerage": "0.15",
        "Exchange transaction charge": "0.00",
        "Securities transaction tax (STT)": "0.15",
        "Stamp duty": "0.02",
        "SEBI turnover fee": "0.00",
        "GST": "0.03",
    }
    assert order.charges_total == D("0.35")
    assert order.charges[0]["native_amount"] == "12.50"
    assert order.charges[0]["native_currency"] == "INR"
    # cash 100000 - 149.70 - 0.35 = 99849.95
    assert engine.get_account(db).cash == D("99849.95")


def test_buy_needs_cash_for_the_charges_too(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    account = engine.get_account(db)
    account.cash = D("12520")  # covers the 12500 of shares but not the 29.59 on top
    db.commit()
    with pytest.raises(InsufficientFunds) as exc:
        place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    assert "12,529.59" in exc.value.message
    assert "12,520.00" in exc.value.message
    assert db.scalars(select(Order)).all() == []


def test_limit_buy_cash_check_includes_charges_at_the_limit_price(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    account = engine.get_account(db)
    account.cash = D("12520")
    db.commit()
    # A limit of 1200 rests (the market is 1250) and is checked at 1200: value 12000,
    # brokerage 12.00, exchange 0.00307% x 12000 = 0.3684 = 0.37, STT 12.00, stamp 1.80,
    # SEBI 0.01, GST 18% x (12.00 + 0.37 + 0.01) = 2.2284 = 2.23 -> charges 28.41,
    # so 12028.41 is needed and 12520 covers it.
    resting = place(
        db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10", type=OrderType.LIMIT, limit_price=D("1200")
    )
    assert resting.status == OrderStatus.OPEN
    assert resting.charges == [] and resting.charges_total == D("0")  # nothing is charged until it fills
    # A limit of 1250 is marketable, fills at once at 1250 and needs 12529.59 > 12520.
    with pytest.raises(InsufficientFunds):
        place(
            db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10", type=OrderType.LIMIT, limit_price=D("1250")
        )


def test_a_resting_limit_order_pays_the_maker_rate_and_a_market_order_the_taker_rate(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    real = brokers.get_broker("binance")
    maker_taker = Fee("Trading fee", "brokerage", "d", percent=D("0.2"), maker_percent=D("0.1"))
    monkeypatch.setattr(brokers, "get_broker", lambda code: replace(real, fees=[maker_taker]))
    account = engine.get_account(db)
    account.broker_crypto = "binance"
    db.commit()

    # Limit buy 0.1 BTC at 50000 while the market is 60000: it rests.
    resting = place(
        db, fake_provider, OrderSide.BUY, "BTC-USD", "0.1", type=OrderType.LIMIT, limit_price=D("50000")
    )
    assert resting.status == OrderStatus.OPEN
    preview = engine.preview_order(
        live(db, fake_provider),
        symbol="BTC-USD",
        side="buy",
        type="limit",
        quantity=D("0.1"),
        limit_price=D("50000"),
    )
    # costed at the limit price as a maker: 0.1 x 50000 = 5000; 0.1% = 5.00
    assert preview.maker is True
    assert preview.charges_total == D("5.00")

    # A market order takes liquidity: 0.1 x 60000 = 6000; 0.2% = 12.00
    taker = place(db, fake_provider, OrderSide.BUY, "BTC-USD", "0.1")
    assert taker.charges_total == D("12.00")

    # The resting order fills later at the then-current price, still as a maker.
    fake_provider.set_price("BTC-USD", D("49000"))
    assert engine.fill_open_orders(live(db, fake_provider)) == 1
    # 0.1 x 49000 = 4900; maker 0.1% = 4.90
    assert resting.status == OrderStatus.FILLED
    assert resting.charges_total == D("4.90")

    # A limit order that is marketable when placed is a taker, and is costed at the market price.
    now = place(
        db, fake_provider, OrderSide.BUY, "BTC-USD", "0.1", type=OrderType.LIMIT, limit_price=D("55000")
    )
    # market is 49000: 4900 x 0.2% = 9.80
    assert now.status == OrderStatus.FILLED
    assert now.charges_total == D("9.80")


def test_preview_and_fill_agree_field_by_field(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    for side, qty in ((OrderSide.BUY, "10"), (OrderSide.SELL, "4")):
        before = engine.get_account(db).cash
        preview = engine.preview_order(
            live(db, fake_provider), symbol="RELIANCE.NS", side=side, type="market", quantity=D(qty)
        )
        order = place(db, fake_provider, side, "RELIANCE.NS", qty)
        assert [ChargeOut.model_validate(c).model_dump(mode="json") for c in preview.charges] == order.charges
        assert preview.charges_total == order.charges_total
        assert preview.value_account == order.amount
        assert preview.fx_rate == order.fx_rate
        assert preview.price == order.fill_price
        assert engine.get_account(db).cash - before == preview.cash_change


def test_a_broker_that_does_not_offer_the_market_is_refused_with_a_sentence(
    db: Session, fake_provider: FakeProvider
):
    engine.update_brokers(live(db, FakeProvider()), {"international": "vested"})
    with pytest.raises(BrokerNotAvailable) as exc:
        place(db, fake_provider, OrderSide.BUY, "VOD.L", "10")
    assert exc.value.message == (
        "Vested only offers US stocks. Choose Interactive Brokers in Settings to trade London shares."
    )
    # Preview refuses the same way, and nothing was written.
    with pytest.raises(BrokerNotAvailable):
        engine.preview_order(
            live(db, fake_provider), symbol="VOD.L", side="buy", type="market", quantity=D(1)
        )
    assert db.scalars(select(Order)).all() == []
    # A resting limit order is refused up front too, rather than rejected later.
    with pytest.raises(BrokerNotAvailable):
        place(db, fake_provider, OrderSide.BUY, "VOD.L", "10", type=OrderType.LIMIT, limit_price=D("0.5"))
    # And Indian brokers offer only Indian markets
    engine.update_brokers(live(db, FakeProvider()), {"india": "zerodha"})
    assert place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "1").status == OrderStatus.FILLED


def test_unknown_exchange_suffix_is_refused(db: Session, fake_provider: FakeProvider):
    fake_provider._instruments["FOO.ZZ"] = Instrument("FOO.ZZ", "Foo", "ZZX", "equity", "USD")
    fake_provider._price["FOO.ZZ"] = fake_provider._previous["FOO.ZZ"] = D("10")
    with pytest.raises(UnsupportedMarket):
        engine.preview_order(
            live(db, fake_provider), symbol="FOO.ZZ", side="buy", type="market", quantity=D(1)
        )


def test_update_brokers_validates_the_segment_and_changes_nothing_on_error(db: Session):
    with pytest.raises(InvalidBroker) as exc:
        engine.update_brokers(live(db, FakeProvider()), {"international": "vested", "india": "ibkr"})
    assert "'ibkr' isn't a broker for Indian stocks" in exc.value.message
    assert "zerodha" in exc.value.message
    with pytest.raises(InvalidBroker):
        engine.update_brokers(live(db, FakeProvider()), {"crypto": "nonexistent"})
    account = engine.get_account(db)
    # the valid half of the failed request was not applied
    assert (account.broker_india, account.broker_international, account.broker_crypto) == (
        "groww",
        "ibkr",
        "coindcx",
    )
    engine.update_brokers(live(db, FakeProvider()), {"crypto": "binance", "india": None})
    assert engine.get_account(db).broker_crypto == "binance"


def test_break_even_price_closes_at_zero_and_one_tick_lower_loses(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    (view,) = engine.get_portfolio(live(db, fake_provider)).holdings
    be = view.break_even_price
    # Cost 12529.59; exit charges are ~0.222% plus Rs 23.60, so about 1258.11 (see test_fees)
    assert D("1258.05") < be < D("1258.15")

    def realized_selling_at(exit_price: Decimal) -> Decimal:
        engine.reset_account(live(db, FakeProvider()))
        fake_provider.set_price("RELIANCE.NS", D("1250"))
        place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
        fake_provider.set_price("RELIANCE.NS", exit_price)
        return place(db, fake_provider, OrderSide.SELL, "RELIANCE.NS", "10").realized_pnl

    assert realized_selling_at(be) >= 0
    assert realized_selling_at(be - D("0.01")) < 0


def test_portfolio_totals_charges_by_category_and_keeps_the_identity(
    db: Session, fake_provider: FakeProvider
):
    inr_account(db)
    place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    paid = engine.get_portfolio(live(db, fake_provider)).charges_paid
    # buy: brokerage 12.50; tax = STT 12.50 + stamp 1.88 = 14.38; exchange 0.38;
    #      regulatory 0.01; GST 2.32; total 29.59
    assert paid.by_category == {
        "brokerage": D("12.50"),
        "tax": D("14.38"),
        "exchange": D("0.38"),
        "regulatory": D("0.01"),
        "depository": D("0"),
        "gst": D("2.32"),
        "fx": D("0"),
    }
    assert paid.total == D("29.59")

    fake_provider.set_price("RELIANCE.NS", D("1300"))
    sell = place(db, fake_provider, OrderSide.SELL, "RELIANCE.NS", "4")
    # 4 x 1300 = 5200: brokerage 5.20, STT 5.20, exchange 0.00307% x 5200 = 0.1596 = 0.16,
    # SEBI 0.0052 = 0.01, DP 20.00, GST 18% x (5.20 + 0.16 + 0.01 + 20.00) = 18% x 25.37 = 4.5666 = 4.57
    # -> 5.20 + 5.20 + 0.16 + 0.01 + 20.00 + 4.57 = 35.14
    assert sell.charges_total == D("35.14")
    pf = engine.get_portfolio(live(db, fake_provider))
    # Whatever the sell cost, realized + unrealized is still exactly the change in wealth.
    assert pf.realized_pnl + pf.unrealized_pnl == pf.total_pnl
    assert pf.total_pnl == pf.total_value - pf.starting_cash
    assert pf.charges_paid.total == D("64.73")  # 29.59 + 35.14
    # realized: proceeds 5200 - 35.14 = 5164.86, against cost out 12529.59 x 4/10 = 5011.836 = 5011.84
    assert sell.realized_pnl == D("153.02")
    # 6 shares left: cost 12529.59 - 5011.84 = 7517.75; value 6 x 1300 = 7800 -> unrealized 282.25
    (view,) = pf.holdings
    assert view.cost_basis == D("7517.75")
    assert view.unrealized_pnl == D("282.25")
    # 153.02 + 282.25 = 435.27 = (992,635.27 cash + 7800 shares) - 1,000,000 started with
    assert pf.total_pnl == D("435.27")


def test_charges_json_is_exactly_the_api_model(db: Session, fake_provider: FakeProvider):
    inr_account(db)
    order = place(db, fake_provider, OrderSide.BUY, "RELIANCE.NS", "10")
    for stored in order.charges:
        assert set(stored) == set(ChargeOut.model_fields)
        assert ChargeOut.model_validate(stored).model_dump(mode="json") == stored
        assert all(isinstance(stored[k], str) for k in ("amount", "native_amount"))


def test_zero_costs_fixture_runs_the_same_code_and_finds_nothing_to_charge(
    db: Session, fake_provider: FakeProvider, zero_costs: None
):
    order = place(db, fake_provider, OrderSide.BUY, "AAPL", "10")
    assert order.charges == []
    assert order.charges_total == D("0")
    assert engine.get_account(db).cash == D("97700.00")
