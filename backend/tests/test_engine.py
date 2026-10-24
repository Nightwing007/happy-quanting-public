"""Engine tests. Fake prices: AAPL 230, RELIANCE.NS 1250 INR, BTC-USD 60000, INRUSD=X 0.011976.

Every expected figure is worked out in the comment above the assertion. If one disagrees with
the code, recompute it by hand before touching the engine.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.base import DataUnavailable
from app.market_data.fake import FakeProvider
from app.models import Order, OrderSide, OrderStatus, OrderType, Trade, TradeStatus, WatchlistItem
from app.trading import engine
from app.trading.engine import live_context as live
from app.trading.errors import (
    InsufficientFunds,
    InsufficientShares,
    InvalidOrder,
    NotTradable,
    OrderNotFound,
    OrderNotOpen,
    ShortNotOffered,
)
from app.trading.money import trim8

D = Decimal

# These tests are about orders, cash and positions, not about what a broker charges.
pytestmark = pytest.mark.usefixtures("zero_costs")


def buy(db: Session, provider: FakeProvider, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.BUY, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def sell(db: Session, provider: FakeProvider, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.SELL, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def open_trades(db: Session, symbol: str) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade)
            .where(Trade.symbol == symbol, Trade.status == TradeStatus.OPEN)
            .order_by(Trade.id)
        )
    )


def position(db: Session, symbol: str) -> SimpleNamespace | None:
    """The open trades of a symbol pooled the way a holding is (None if there are none)."""
    trades = open_trades(db, symbol)
    if not trades:
        return None
    quantity = sum((t.open_quantity for t in trades), D(0))
    avg = sum((t.open_quantity * t.entry_price for t in trades), D(0)) / quantity
    return SimpleNamespace(
        quantity=quantity,
        avg_price=trim8(avg),
        cost_basis=sum((t.cost_basis for t in trades), D(0)),
        currency=trades[0].currency,
    )


def snapshot(db: Session):
    account = engine.get_account(db)
    trades = [(t.symbol, t.open_quantity, t.entry_price, t.cost_basis) for t in db.scalars(select(Trade))]
    return account.cash, account.realized_pnl, trades, db.scalars(select(Order)).all()


def test_buying_lowers_cash(db: Session, fake_provider: FakeProvider):
    order = buy(db, fake_provider, "AAPL", "10")
    # 10 x 230 = 2300; 100000 - 2300 = 97700
    assert order.status == OrderStatus.FILLED
    assert order.amount == D("2300.00")
    assert order.fill_price == D("230")
    assert engine.get_account(db).cash == D("97700.00")
    pos = position(db, "AAPL")
    assert (pos.quantity, pos.avg_price, pos.cost_basis) == (D("10"), D("230"), D("2300.00"))


def test_average_cost_across_two_buys(db: Session, fake_provider: FakeProvider):
    fake_provider.set_price("AAPL", D("100"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("110"))
    buy(db, fake_provider, "AAPL", "10")
    # cost 1000 + 1100 = 2100; avg = 2100 / 20 = 105; cash 100000 - 2100 = 97900
    # (two trades, one per fill; the pooled holding is what shows 20 at 105)
    assert len(open_trades(db, "AAPL")) == 2
    pos = position(db, "AAPL")
    assert (pos.quantity, pos.avg_price, pos.cost_basis) == (D("20"), D("105"), D("2100.00"))
    assert engine.get_account(db).cash == D("97900.00")


def test_selling_part_realizes_profit(db: Session, fake_provider: FakeProvider):
    fake_provider.set_price("AAPL", D("100"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("110"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("120"))
    order = sell(db, fake_provider, "AAPL", "5")
    # A sell closes the oldest lot first: 5 of the 10 bought at 100.
    # proceeds 5 x 120 = 600; cost out = 1000 x 5/10 = 500; realized 100
    # left: 5 at 100 (cost 500) and 10 at 110 (cost 1100): 15 shares, cost 1600,
    # avg = (5 x 100 + 10 x 110) / 15 = 1600 / 15 = 106.66666667; cash 97900 + 600 = 98500
    assert order.amount == D("600.00")
    assert order.realized_pnl == D("100.00")
    pos = position(db, "AAPL")
    assert (pos.quantity, pos.avg_price, pos.cost_basis) == (D("15"), D("106.66666667"), D("1600.00"))
    account = engine.get_account(db)
    assert account.cash == D("98500.00")
    assert account.realized_pnl == D("100.00")


def test_selling_everything_closes_position(db: Session, fake_provider: FakeProvider):
    fake_provider.set_price("AAPL", D("100"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("110"))
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("120"))
    order = sell(db, fake_provider, "AAPL", "20")
    # proceeds 20 x 120 = 2400; cost 2100; realized 300; cash 97900 + 2400 = 100300
    assert position(db, "AAPL") is None
    assert order.realized_pnl == D("300.00")
    account = engine.get_account(db)
    assert account.realized_pnl == D("300.00")
    assert account.cash == D("100300.00")
    assert account.cash - account.starting_cash == account.realized_pnl


def test_insufficient_cash_rejected_and_changes_nothing(db: Session, fake_provider: FakeProvider):
    buy(db, fake_provider, "AAPL", "10")
    before = snapshot(db)
    with pytest.raises(InsufficientFunds) as exc:
        buy(db, fake_provider, "AAPL", "500")  # 500 x 230 = 115000 > 97700 cash
    assert "115,000.00" in exc.value.message
    assert "97,700.00" in exc.value.message
    after = snapshot(db)
    assert after[:3] == before[:3]
    assert len(after[3]) == len(before[3]) == 1


def test_cannot_sell_more_than_held_where_shorting_is_not_offered(db: Session, fake_provider: FakeProvider):
    # Xetra (SAP.DE) has no short rule, so a sell can only close what is held. (On a market that
    # allows shorts the surplus becomes a short instead; see test_shorting.py.)
    with pytest.raises(ShortNotOffered):
        sell(db, fake_provider, "SAP.DE", "1")  # holds nothing
    buy(db, fake_provider, "SAP.DE", "10")
    with pytest.raises(InsufficientShares):
        sell(db, fake_provider, "SAP.DE", "11")
    assert position(db, "SAP.DE").quantity == D("10")


def test_shares_promised_to_open_sell_cannot_be_sold_twice(db: Session, fake_provider: FakeProvider):
    buy(db, fake_provider, "SAP.DE", "10")
    sell(db, fake_provider, "SAP.DE", "6", type=OrderType.LIMIT, limit_price=D("300"))  # stays open
    # free = 10 held - 6 promised = 4 (SAP.DE can't be shorted, so the surplus is refused)
    with pytest.raises(InsufficientShares) as exc:
        sell(db, fake_provider, "SAP.DE", "5")
    assert "only 4 are free" in exc.value.message
    assert sell(db, fake_provider, "SAP.DE", "4").status == OrderStatus.FILLED


def test_index_and_currency_are_not_tradable(db: Session, fake_provider: FakeProvider):
    with pytest.raises(NotTradable) as exc:
        buy(db, fake_provider, "^GSPC", "1")
    assert "is an index, which can be charted but not traded" in exc.value.message
    with pytest.raises(NotTradable) as exc:
        buy(db, fake_provider, "EURUSD=X", "1")
    assert "is a currency" in exc.value.message
    assert snapshot(db)[3] == []


def test_limit_buy_waits_then_fills_at_current_price(db: Session, fake_provider: FakeProvider):
    order = buy(db, fake_provider, "AAPL", "10", type=OrderType.LIMIT, limit_price=D("200"))
    assert order.status == OrderStatus.OPEN  # 230 > 200
    assert engine.fill_open_orders(live(db, fake_provider)) == 0
    assert engine.get_account(db).cash == D("100000")
    fake_provider.set_price("AAPL", D("195"))
    assert engine.fill_open_orders(live(db, fake_provider)) == 1
    # fills at 195, not the 200 limit: 10 x 195 = 1950; cash 98050
    assert order.status == OrderStatus.FILLED
    assert order.fill_price == D("195")
    assert order.amount == D("1950.00")
    assert engine.get_account(db).cash == D("98050.00")


def test_limit_sell_waits_then_fills(db: Session, fake_provider: FakeProvider):
    buy(db, fake_provider, "AAPL", "10")
    order = sell(db, fake_provider, "AAPL", "10", type=OrderType.LIMIT, limit_price=D("250"))
    assert order.status == OrderStatus.OPEN  # 230 < 250
    fake_provider.set_price("AAPL", D("260"))
    assert engine.fill_open_orders(live(db, fake_provider)) == 1
    # 10 x 260 = 2600; cost 2300; realized 300; cash 100000 - 2300 + 2600 = 100300
    assert order.fill_price == D("260")
    assert order.realized_pnl == D("300.00")
    assert engine.get_account(db).cash == D("100300.00")
    assert position(db, "AAPL") is None


def test_marketable_limit_fills_immediately(db: Session, fake_provider: FakeProvider):
    order = buy(db, fake_provider, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("240"))
    assert order.status == OrderStatus.FILLED
    assert order.fill_price == D("230")  # better than the limit


def test_cancel_order(db: Session, fake_provider: FakeProvider):
    order = buy(db, fake_provider, "AAPL", "10", type=OrderType.LIMIT, limit_price=D("200"))
    assert engine.cancel_order(live(db, FakeProvider()), order.id).status == OrderStatus.CANCELLED
    with pytest.raises(OrderNotOpen):
        engine.cancel_order(live(db, FakeProvider()), order.id)
    with pytest.raises(OrderNotFound):
        engine.cancel_order(live(db, FakeProvider()), 999)
    fake_provider.set_price("AAPL", D("150"))
    assert engine.fill_open_orders(live(db, fake_provider)) == 0  # a cancelled order never fills


def test_reset_restores_starting_cash(db: Session, fake_provider: FakeProvider):
    buy(db, fake_provider, "AAPL", "10")
    fake_provider.set_price("AAPL", D("300"))
    sell(db, fake_provider, "AAPL", "5")
    engine.reset_account(live(db, FakeProvider()))
    account = engine.get_account(db)
    assert account.cash == D("100000")
    assert account.realized_pnl == D("0")
    assert db.scalars(select(Trade)).all() == []
    assert db.scalars(select(Order)).all() == []
    assert len(db.scalars(select(WatchlistItem)).all()) == 4  # watchlist survives


def test_first_run_setup_is_idempotent(db: Session):
    engine.first_run_setup(db)
    engine.first_run_setup(db)
    account = engine.get_account(db)
    assert account.cash == account.starting_cash == D("100000")
    symbols = [w.symbol for w in db.scalars(select(WatchlistItem).order_by(WatchlistItem.id))]
    assert symbols == ["AAPL", "RELIANCE.NS", "BTC-USD", "^GSPC"]


def test_foreign_currency_buy_converts_at_fx_rate(db: Session, fake_provider: FakeProvider):
    order = buy(db, fake_provider, "RELIANCE.NS", "10")
    # 10 x 1250 INR = 12500 INR; x 0.011976 USD/INR = 149.70 USD; cash 100000 - 149.70 = 99850.30
    assert order.currency == "INR"
    assert order.fill_price == D("1250")
    assert order.fx_rate == D("0.011976")
    assert order.amount == D("149.70")
    assert engine.get_account(db).cash == D("99850.30")
    pos = position(db, "RELIANCE.NS")
    assert (pos.currency, pos.avg_price, pos.cost_basis) == ("INR", D("1250"), D("149.70"))


def test_limit_order_unaffordable_at_fill_time_is_rejected(db: Session, fake_provider: FakeProvider):
    # Placement check: 400 x 200 limit = 80000 <= 100000, so it is accepted and stays open.
    waiting = buy(db, fake_provider, "AAPL", "400", type=OrderType.LIMIT, limit_price=D("200"))
    assert waiting.status == OrderStatus.OPEN
    buy(db, fake_provider, "AAPL", "300")  # 300 x 230 = 69000; cash left 31000
    before = snapshot(db)
    fake_provider.set_price("AAPL", D("190"))
    # Fill would cost 400 x 190 = 76000 > 31000 cash.
    assert engine.fill_open_orders(live(db, fake_provider)) == 0
    assert waiting.status == OrderStatus.REJECTED
    assert "76,000.00" in waiting.reject_reason
    after = snapshot(db)
    assert after[:3] == before[:3]
    assert engine.get_account(db).cash == D("31000.00")


def test_open_order_stays_open_when_price_unavailable(db: Session, fake_provider: FakeProvider, monkeypatch):
    order = buy(db, fake_provider, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("200"))

    def boom(symbol: str):
        raise DataUnavailable()

    monkeypatch.setattr(fake_provider, "get_quote", boom)
    assert engine.fill_open_orders(live(db, fake_provider)) == 0
    assert order.status == OrderStatus.OPEN


def test_portfolio_totals_and_identity(db: Session, fake_provider: FakeProvider):
    buy(db, fake_provider, "AAPL", "10")  # 2300
    buy(db, fake_provider, "RELIANCE.NS", "10")  # 149.70
    fake_provider.set_price("AAPL", D("250"))
    sell(db, fake_provider, "AAPL", "4")
    # sell proceeds 4 x 250 = 1000; cost out 2300 x 4/10 = 920; realized 80
    # AAPL left: 6 shares, cost 1380, value 6 x 250 = 1500, unrealized 120 (120/1380 = 8.70%)
    # RELIANCE: value 10 x 1250 x 0.011976 = 149.70, unrealized 0
    # cash = 100000 - 2300 - 149.70 + 1000 = 98550.30
    # market value 1649.70; total 98550.30 + 1649.70 = 100200.00; total pnl 200 = 80 + 120
    pf = engine.get_portfolio(live(db, fake_provider))
    assert pf.cash == D("98550.30")
    assert pf.invested == D("1529.70")  # 1380 + 149.70
    assert pf.market_value == D("1649.70")
    assert pf.total_value == D("100200.00")
    assert pf.realized_pnl == D("80.00")
    assert pf.unrealized_pnl == D("120.00")
    assert pf.total_pnl == D("200.00")
    assert pf.realized_pnl + pf.unrealized_pnl == pf.total_pnl
    aapl = next(p for p in pf.holdings if p.symbol == "AAPL")
    assert (aapl.market_value, aapl.unrealized_pnl, aapl.unrealized_pct) == (
        D("1500.00"), D("120.00"), D("8.70"),
    )  # fmt: skip


def test_portfolio_values_at_cost_when_quote_fails(db: Session, fake_provider: FakeProvider, monkeypatch):
    buy(db, fake_provider, "AAPL", "10")
    real = fake_provider.get_quote

    def flaky(symbol: str):
        if symbol == "AAPL":
            raise DataUnavailable()
        return real(symbol)

    monkeypatch.setattr(fake_provider, "get_quote", flaky)
    pf = engine.get_portfolio(live(db, fake_provider))
    (view,) = pf.holdings
    assert view.price_unavailable is True
    assert view.market_value == D("2300.00")  # at cost
    assert view.unrealized_pnl == D("0")
    assert pf.total_value == D("100000.00")


def test_timestamps_use_the_fixed_clock(db: Session, fake_provider: FakeProvider, fixed_clock: datetime):
    order = buy(db, fake_provider, "AAPL", "1")
    assert order.created_at == fixed_clock
    assert order.filled_at == fixed_clock
    assert engine.get_account(db).created_at == fixed_clock


@pytest.mark.parametrize(
    ("quantity", "type_", "limit_price"),
    [
        ("0", OrderType.MARKET, None),
        ("-1", OrderType.MARKET, None),
        ("0.000000001", OrderType.MARKET, None),  # 9 dp
        ("1", OrderType.LIMIT, None),
        ("1", OrderType.LIMIT, D("0")),
        ("1", OrderType.MARKET, D("100")),
    ],
)
def test_invalid_orders_raise_and_write_nothing(
    db: Session, fake_provider: FakeProvider, quantity, type_, limit_price
):
    with pytest.raises(InvalidOrder):
        buy(db, fake_provider, "AAPL", quantity, type=type_, limit_price=limit_price)
    assert db.scalars(select(Order)).all() == []


def test_trading_code_never_reads_the_wall_clock():
    trading_dir = Path(__file__).resolve().parent.parent / "app" / "trading"
    files = list(trading_dir.glob("*.py"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "datetime.now(" not in text, path.name
        assert "datetime.utcnow(" not in text, path.name
