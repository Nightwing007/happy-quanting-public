"""The paper-trading engine: orders, trades, fills, short selling, portfolio valuation.

Unit of work: every public function here that writes commits before it returns, and rolls
back on failure, so callers (routes, the background task) never commit.

An order is turned into legs by `_plan`: a sell closes your open longs (oldest first) and only
the rest becomes a short; a buy closes your open shorts first and only the rest becomes a long;
an exit names the trade to close. Each leg is charged under its own product. An order placed
while its market is closed is accepted and waits, like a broker's after-market order, and fills
at the first fresh quote after the open (an intraday short is the exception: it can't wait).

Every cost goes through `plan_cost`: the preview, the cash check when an order is placed and
the fill all call it, so what you are quoted is what you are charged.

The books balance by construction. Cash, margin and the realized total move together in `_fill`
and `accrue_financing`, and every trade keeps `cost_basis = entry_value + entry_charges`, so
realized + unrealized is exactly total value less starting cash, to the paisa, with shorts open.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.market_data import get_quotes
from app.market_data.base import TRADABLE_TYPES, MarketDataError, MarketDataProvider, Quote
from app.market_data.fx import get_fx_rate
from app.models import (
    Account,
    ClosedHow,
    LegKind,
    Order,
    OrderOrigin,
    OrderSide,
    OrderStatus,
    OrderType,
    Trade,
    TradeDirection,
    TradeProduct,
    TradeStatus,
    WatchlistItem,
)
from app.schemas import ChargeOut, OrderLegOut, PayoutOut, PayoutsOut, PayoutTotalsOut

from . import brokers as broker_data
from . import hours
from . import markets as market_data
from .brokers import Broker
from .errors import (
    BrokerNotAvailable,
    InsufficientFunds,
    InsufficientShares,
    InvalidBroker,
    InvalidOrder,
    NotTradable,
    OrderNotFound,
    OrderNotOpen,
    ProtectionInvalid,
    ShortMarketClosed,
    ShortNotOffered,
    ShortQuantityInvalid,
    TradeNotFound,
    TradeNotOpen,
    TradingError,
)
from .fees import CATEGORIES, Charge, break_even_cover_price, break_even_price, calculate_charges
from .markets import Market
from .money import money, trim8

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
_MAX_QUANTITY_DP = 8
_OPENING = (LegKind.OPEN_LONG, LegKind.OPEN_SHORT)
_OWN_TRADE_ORIGINS = (OrderOrigin.SQUARE_OFF, OrderOrigin.STOP_LOSS, OrderOrigin.TARGET)
PROTECTION_DAYS = 365  # like a GTT: a stop or target lapses after a year

STARTER_WATCHLIST = [
    ("AAPL", "Apple Inc."),
    ("RELIANCE.NS", "Reliance Industries"),
    ("BTC-USD", "Bitcoin USD"),
    ("^GSPC", "S&P 500"),
]


# --- account ---------------------------------------------------------------------------


def first_run_setup(db: Session) -> None:
    """Create the account and starter watchlist if there is no account yet. Idempotent."""
    if db.scalar(select(Account.id).limit(1)) is not None:
        return
    settings = get_settings()
    now = clock.now()
    account = Account(
        currency=settings.base_currency,
        cash=settings.starting_cash,
        starting_cash=settings.starting_cash,
        realized_pnl=ZERO,
        margin_used=ZERO,
        created_at=now,
    )
    db.add(account)
    db.flush()
    for symbol, name in STARTER_WATCHLIST:
        db.add(WatchlistItem(account_id=account.id, symbol=symbol, name=name, created_at=now))
    db.commit()


def get_account(db: Session) -> Account:
    account = db.scalar(select(Account).order_by(Account.id).limit(1))
    if account is None:
        first_run_setup(db)
        account = db.scalar(select(Account).order_by(Account.id).limit(1))
    assert account is not None
    return account


def reset_account(db: Session) -> Account:
    """Wipe orders and trades and restore the starting cash. The watchlist is kept."""
    account = get_account(db)
    db.execute(delete(Order).where(Order.account_id == account.id))
    db.execute(delete(Trade).where(Trade.account_id == account.id))
    account.cash = account.starting_cash
    account.realized_pnl = ZERO
    account.margin_used = ZERO
    db.commit()
    return account


# Money fields of an order leg, which `convert_account_currency` has to move with the rest.
_LEG_MONEY = ("value", "charges_total", "entry_charges", "cash_change", "margin_change", "realized_pnl")


def convert_account_currency(db: Session, provider: MarketDataProvider, to_currency: str) -> bool:
    """Re-denominate the whole account in `to_currency` at the current FX rate. Returns whether it
    converted. Does nothing if the account is already in that currency, or if the rate is
    unavailable (logged; the app still starts and the account is left as it was).

    Every account-currency money field moves together in one transaction: cash, margin, starting
    cash, realized P&L, each order's amounts, charge lines and legs, each trade's values. Figures
    in the instrument's own currency (prices, native charge amounts, average cost) do not change.
    """
    account = get_account(db)
    old = account.currency
    if old == to_currency:
        return False
    try:
        rate = _fx_to_account(provider, old, to_currency)
    except MarketDataError as exc:
        logger.warning(
            "Account is in %s but BASE_CURRENCY is %s, and the %s to %s rate is unavailable (%s). "
            "Leaving the account unchanged.",
            old, to_currency, old, to_currency, exc.message,
        )  # fmt: skip
        return False

    def convert(value: Decimal) -> Decimal:
        return money(value * rate)

    def convert_text(text: str) -> str:
        return f"{convert(Decimal(text)):f}"

    old_cash, old_starting = account.cash, account.starting_cash
    try:
        account.cash = convert(account.cash)
        account.starting_cash = convert(account.starting_cash)
        account.realized_pnl = convert(account.realized_pnl)
        orders = db.scalars(select(Order).where(Order.account_id == account.id)).all()
        for order in orders:
            if order.amount is not None:
                order.amount = convert(order.amount)
            order.charges_total = convert(order.charges_total)
            order.cash_change = convert(order.cash_change)
            if order.realized_pnl is not None:
                order.realized_pnl = convert(order.realized_pnl)
            order.charges = [{**line, "amount": convert_text(line["amount"])} for line in order.charges]
            order.legs = [
                {
                    **leg,
                    **{k: convert_text(leg[k]) for k in _LEG_MONEY if leg.get(k) is not None},
                    "charges": [{**line, "amount": convert_text(line["amount"])} for line in leg["charges"]],
                }
                for leg in order.legs
            ]
            if order.fx_rate is not None:
                # instrument -> old account currency, now instrument -> new one.
                order.fx_rate = Decimal(1) if order.currency == to_currency else trim8(order.fx_rate * rate)
        trades = db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
        for trade in trades:
            trade.cost_basis = convert(trade.cost_basis)
            trade.entry_charges = convert(trade.entry_charges)
            # Derived, so cost_basis = entry_value + entry_charges still holds to the paisa.
            trade.entry_value = trade.cost_basis - trade.entry_charges
            for name in ("margin_blocked", "financing_paid", "exit_value", "exit_charges", "realized_pnl"):
                setattr(trade, name, convert(getattr(trade, name)))
            trade.entry_fx_rate = (
                Decimal(1) if trade.currency == to_currency else trim8(trade.entry_fx_rate * rate)
            )
        account.margin_used = sum(
            (t.margin_blocked for t in trades if t.status == TradeStatus.OPEN), ZERO
        )
        account.currency = to_currency
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info(
        "Converted account from %s to %s at %s: cash %s → %s, starting cash %s → %s, "
        "%d order(s) and %d trade(s) converted",
        old, to_currency, f"{rate:,.2f}", f"{old_cash:,.2f}", f"{account.cash:,.2f}",
        f"{old_starting:,.2f}", f"{account.starting_cash:,.2f}", len(orders), len(trades),
    )  # fmt: skip
    return True


def update_brokers(db: Session, choices: dict[str, str | None]) -> Account:
    """Set the broker for each segment named in `choices` (segment -> broker code). Checks every
    choice before changing any, so a bad one leaves the account as it was."""
    chosen = {segment: code for segment, code in choices.items() if code is not None}
    for segment, code in chosen.items():
        try:
            valid = broker_data.get_broker(code).segment == segment
        except KeyError:
            valid = False
        if not valid:
            options = ", ".join(b.code for b in broker_data.brokers_for_segment(segment))
            label = broker_data.SEGMENT_LABELS[segment]
            raise InvalidBroker(f"'{code}' isn't a broker for {label}. Choose one of: {options}.")
    account = get_account(db)
    for segment, code in chosen.items():
        setattr(account, f"broker_{segment}", code)
    db.commit()
    return account


# --- planning --------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderRequest:
    """What an order asks for, before it is turned into legs."""

    symbol: str
    side: str
    quantity: Decimal
    exit_trade_id: int | None = None  # set when the order is an exit of that trade
    origin: str = OrderOrigin.USER
    # Shares already promised to other open sell orders; they can't be sold twice. Only counted
    # when an order is placed, never when an order that is itself waiting finally fills.
    promised: Decimal = ZERO


@dataclass
class LegPlan:
    kind: str  # LegKind
    quantity: Decimal
    product: str  # TradeProduct
    trade: Trade | None = None  # the trade a closing leg closes; None for a leg that opens one

    @property
    def side(self) -> str:
        return OrderSide.BUY if self.kind in (LegKind.CLOSE_SHORT, LegKind.OPEN_LONG) else OrderSide.SELL


@dataclass
class Plan:
    request: OrderRequest
    market: Market
    legs: list[LegPlan]
    fifo: bool = False  # an exit that took the oldest lots because the market pools holdings
    note: str = ""


def _open_trades(db: Session, account: Account, symbol: str, direction: str | None = None) -> list[Trade]:
    """Open trades of `symbol`, oldest first."""
    query = select(Trade).where(
        Trade.account_id == account.id, Trade.symbol == symbol, Trade.status == TradeStatus.OPEN
    )
    if direction is not None:
        query = query.where(Trade.direction == direction)
    return list(db.scalars(query.order_by(Trade.opened_at, Trade.id)))


def _promised(db: Session, account: Account, symbol: str) -> Decimal:
    """Shares promised to open sell orders for `symbol`. Summed in Python: quantities are TEXT
    in SQLite, so SQL SUM would turn them into floats."""
    return sum(
        (
            o.quantity
            for o in db.scalars(
                select(Order).where(
                    Order.account_id == account.id,
                    Order.symbol == symbol,
                    Order.side == OrderSide.SELL,
                    Order.status == OrderStatus.OPEN,
                )
            )
        ),
        ZERO,
    )


def _close_legs(trades: list[Trade], quantity: Decimal, kind: str) -> list[LegPlan]:
    """Legs that close `quantity` across `trades`, oldest first."""
    legs: list[LegPlan] = []
    remaining = quantity
    for trade in trades:
        if remaining <= 0:
            break
        take = min(trade.open_quantity, remaining)
        legs.append(LegPlan(kind, take, trade.product, trade))
        remaining -= take
    return legs


def _short_leg(market: Market, request: OrderRequest, short_quantity: Decimal, held: Decimal) -> LegPlan:
    """The leg that opens a short for the part of a sell that closes nothing, or the reason it
    can't. The error type is decided here, with its sentence, so no caller reads words."""
    rule = market.short_rule
    if rule is None:
        if held > 0:
            # They own some, so this is a plain "you don't have that many", not a short attempt.
            raise InsufficientShares(
                _shares_message(request.symbol, held, request.promised, request.quantity)
            )
        raise ShortNotOffered(f"Short selling isn't offered on {market.name} for retail accounts.")
    # The quantity-step rule applies to the short part only: a whole-share sell of a fractional
    # long is fine, and this is never asked about a sell that closes everything it sells.
    if short_quantity % rule.min_shortable_step != 0:
        if rule.min_shortable_step == 1:
            raise ShortQuantityInvalid(
                f"You can only short whole {market.name} shares — nobody lends a fraction of a share."
            )
        raise ShortQuantityInvalid(
            f"Shorts on {market.name} trade in steps of {rule.min_shortable_step:f}."
        )
    if rule.style == "intraday":
        status = hours.market_status(market)
        if not hours.is_open(market):
            raise ShortMarketClosed(
                f"An intraday short can't be placed while {market.name} is closed, because brokers "
                f"take no after-market order for one. {hours.status_label(market, status)}."
            )
    product = TradeProduct.INTRADAY if rule.style == "intraday" else TradeProduct.MARGIN
    return LegPlan(LegKind.OPEN_SHORT, short_quantity, product)


def _get_open_trade(db: Session, account: Account, trade_id: int) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None or trade.account_id != account.id:
        raise TradeNotFound(f"There is no trade with id {trade_id}.")
    if trade.status != TradeStatus.OPEN:
        raise TradeNotOpen(f"Trade {trade_id} is already closed, so there is nothing to exit.")
    return trade


def _plan_exit(db: Session, account: Account, request: OrderRequest, market: Market) -> Plan:
    assert request.exit_trade_id is not None
    trade = _get_open_trade(db, account, request.exit_trade_id)
    kind = LegKind.CLOSE_LONG if trade.direction == TradeDirection.LONG else LegKind.CLOSE_SHORT
    quantity = request.quantity
    # A square-off, stop-loss or target always closes the very trade it belongs to, even where
    # holdings are pooled.
    if market.lot_exits == "specific" or request.origin in _OWN_TRADE_ORIGINS:
        if quantity > trade.open_quantity:
            raise InvalidOrder(
                f"Trade {trade.id} has only {trade.open_quantity:f} {trade.symbol} open, "
                f"so you can't exit {quantity:f} of it."
            )
        return Plan(request, market, [LegPlan(kind, quantity, trade.product, trade)])
    pool = _open_trades(db, account, trade.symbol, trade.direction)
    available = sum((t.open_quantity for t in pool), ZERO)
    if quantity > available:
        raise InvalidOrder(f"You hold only {available:f} {trade.symbol}, so you can't exit {quantity:f}.")
    note = (
        f"{market.name} holdings are pooled, so this exit closes your oldest {trade.symbol} "
        "first (FIFO), whichever trade it was started from."
    )
    return Plan(request, market, _close_legs(pool, quantity, kind), fifo=True, note=note)


def _plan(db: Session, account: Account, request: OrderRequest, quote: Quote) -> Plan:
    """Turn an order into legs, or raise the TradingError that says why it can't be.

    A sell closes open longs first, oldest first, and only the rest becomes a short. A buy
    closes open shorts first and only the rest opens a long. An exit closes the named trade.
    """
    market = market_data.market_for(request.symbol, quote.type)
    if request.exit_trade_id is not None:
        return _plan_exit(db, account, request, market)
    quantity = request.quantity
    if request.side == OrderSide.SELL:
        longs = _open_trades(db, account, request.symbol, TradeDirection.LONG)
        held = sum((t.open_quantity for t in longs), ZERO)
        close_quantity = min(quantity, max(held - request.promised, ZERO))
        legs = _close_legs(longs, close_quantity, LegKind.CLOSE_LONG)
        if quantity > close_quantity:
            legs.append(_short_leg(market, request, trim8(quantity - close_quantity), held))
    else:
        shorts = _open_trades(db, account, request.symbol, TradeDirection.SHORT)
        close_quantity = min(quantity, sum((t.open_quantity for t in shorts), ZERO))
        legs = _close_legs(shorts, close_quantity, LegKind.CLOSE_SHORT)
        if quantity > close_quantity:
            legs.append(LegPlan(LegKind.OPEN_LONG, trim8(quantity - close_quantity), TradeProduct.DELIVERY))
    return Plan(request, market, legs)


# --- costs -----------------------------------------------------------------------------


@dataclass
class LegCost:
    kind: str
    trade: Trade | None  # the trade a closing leg closes
    quantity: Decimal
    product: str
    price: Decimal  # instrument currency
    value: Decimal  # instrument currency
    value_account: Decimal
    charges: list[Charge]
    charges_total: Decimal  # account currency
    cash_change: Decimal
    margin_change: Decimal  # + blocked by an opening short, - released by a cover
    # For a closing leg: what leaves the trade with the part it closes.
    entry_charges: Decimal
    entry_value: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal | None  # closing legs only
    trade_id: int | None = None  # the trade it closes, or (after the fill) the one it opened


@dataclass
class PlanCost:
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal  # the price the figures are worked out at, instrument currency
    currency: str
    fx_rate: Decimal  # instrument currency -> account currency
    value: Decimal  # instrument currency
    value_account: Decimal
    charges: list[Charge]  # all legs, lines with the same name added together
    charges_total: Decimal  # account currency
    cash_change: Decimal  # buy: -(value + charges); sell: +(value - charges); short: -charges
    margin_change: Decimal
    realized_pnl: Decimal | None  # None when nothing closes
    legs: list[LegCost]
    fifo: bool
    note: str
    broker: Broker
    market: Market
    maker: bool


def _not_offered_message(broker: Broker, market: Market) -> str:
    offered = [market_data.MARKETS[c].name for c in broker.markets if c in market_data.MARKETS]
    if len(offered) <= 3:
        what = f"{' and '.join(offered)} stocks"
    else:
        what = f"{len(offered)} markets, not {market.name}"
    message = f"{broker.name} only offers {what}."
    others = [b for b in broker_data.brokers_for_segment(market.segment) if b.offers(market.code)]
    if others:
        message += f" Choose {others[0].name} in Settings to trade {market.name} shares."
    else:
        message += f" None of the brokers here offer {market.name} shares."
    return message


def _broker_for(account: Account, market: Market) -> Broker:
    code = getattr(account, f"broker_{market.segment}")
    try:
        broker = broker_data.get_broker(code)
    except KeyError:
        raise BrokerNotAvailable(
            f"The broker '{code}' chosen in Settings isn't one Happy Quanting knows. "
            "Choose another in Settings."
        ) from None
    if not broker.offers(market.code):
        raise BrokerNotAvailable(_not_offered_message(broker, market))
    return broker


def _split_charges(charges: list[Charge], quantities: list[Decimal]) -> list[list[Charge]]:
    """Share one execution's charge lines between the legs that made it up, by quantity.

    Closing three lots in one sell is one contract at the broker (one brokerage, one depository
    charge), so it is charged once and then split; the last leg takes what is left so the
    shares add up to the whole to the paisa.
    """
    if len(quantities) == 1:
        return [list(charges)]
    total = sum(quantities, ZERO)
    out: list[list[Charge]] = [[] for _ in quantities]
    for charge in charges:
        given_amount = given_native = ZERO
        for i, q in enumerate(quantities):
            if i == len(quantities) - 1:
                amount, native = charge.amount - given_amount, charge.native_amount - given_native
            else:
                amount, native = money(charge.amount * q / total), money(charge.native_amount * q / total)
            given_amount += amount
            given_native += native
            if amount or native:
                out[i].append(
                    Charge(
                        charge.name, charge.category, charge.description,
                        amount, native, charge.native_currency,
                    )
                )  # fmt: skip
    return out


def _allocate(trade: Trade, quantity: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """What leaves `trade` with `quantity` of its open part: (cost basis, entry charges, entry
    value, margin). Each is quantized once; the entry value is what is left of the cost basis,
    so cost basis = entry value + entry charges holds exactly. Closing all of it takes all that
    remains, so nothing is lost to rounding."""
    if quantity == trade.open_quantity:
        return trade.cost_basis, trade.entry_charges, trade.entry_value, trade.margin_blocked
    cost_basis = money(trade.cost_basis * quantity / trade.open_quantity)
    entry_charges = money(trade.entry_charges * quantity / trade.open_quantity)
    margin = money(trade.margin_blocked * quantity / trade.open_quantity)
    return cost_basis, entry_charges, cost_basis - entry_charges, margin


def _merge_charges(legs: list[LegCost]) -> list[Charge]:
    merged: dict[tuple[str, str, str], Charge] = {}
    for leg in legs:
        for c in leg.charges:
            key = (c.name, c.category, c.native_currency)
            if key in merged:
                m = merged[key]
                merged[key] = Charge(
                    m.name, m.category, m.description, m.amount + c.amount,
                    m.native_amount + c.native_amount, m.native_currency,
                )  # fmt: skip
            else:
                merged[key] = c
    return list(merged.values())


def plan_cost(
    provider: MarketDataProvider,
    account: Account,
    plan: Plan,
    quote: Quote,
    *,
    price: Decimal,
    order_type: str,
    resting: bool = False,
) -> PlanCost:
    """What a plan costs and what it does to cash and margin. The only place charges are worked
    out: preview, the placement check and the fill all call this.

    Legs that execute the same way (same side, same product) are one contract, so they are
    charged together and the lines split between them. A leg in another product is another
    contract with its own charges: closing a delivery long pays delivery charges with the
    depository fee, the intraday short that follows it pays intraday ones.

    `resting` is true for a limit order that waited in the book and was then hit, which is the
    only case that counts as a maker. A market order, or a limit order that is marketable the
    moment it is placed, takes liquidity.
    """
    market = plan.market
    broker = _broker_for(account, market)
    price = trim8(price)
    fx = _fx_to_account(provider, quote.currency, account.currency)
    maker = order_type == OrderType.LIMIT and resting

    groups: dict[tuple[str, str], list[int]] = {}
    for index, leg in enumerate(plan.legs):
        groups.setdefault((leg.side, leg.product), []).append(index)
    leg_charges: dict[int, list[Charge]] = {}
    for (side, product), indexes in groups.items():
        quantities = [plan.legs[i].quantity for i in indexes]
        charges = calculate_charges(
            market,
            broker,
            side,
            sum(quantities, ZERO),
            price,
            instrument_type=quote.type,
            instrument_currency=quote.currency,
            account_currency=account.currency,
            fx_rate=fx,
            maker=maker,
            product=product,
        )
        for i, share in zip(indexes, _split_charges(charges, quantities), strict=True):
            leg_charges[i] = share

    costs: list[LegCost] = []
    for index, leg in enumerate(plan.legs):
        charges = leg_charges[index]
        total = sum((c.amount for c in charges), ZERO)
        value_account = money(leg.quantity * price * fx)
        basis_out = charges_out = value_out = margin_out = ZERO
        realized: Decimal | None = None
        margin_change = ZERO
        if leg.kind == LegKind.OPEN_LONG:
            cash_change = -(value_account + total)
        elif leg.kind == LegKind.OPEN_SHORT:
            rule = market.short_rule
            assert rule is not None
            # Proceeds are not paid out: a slice of cash is blocked as margin instead.
            cash_change = -total
            margin_change = money(value_account * rule.margin_percent / HUNDRED)
        else:
            assert leg.trade is not None
            basis_out, charges_out, value_out, margin_out = _allocate(leg.trade, leg.quantity)
            if leg.kind == LegKind.CLOSE_LONG:
                cash_change = value_account - total
                # Net proceeds against the cost (entry charges included) of the shares leaving: a
                # round trip at an unchanged price realizes exactly minus both ends' charges.
                realized = cash_change - basis_out
            else:
                # The short took in value_out when it was opened; covering pays value_account.
                cash_change = (value_out - value_account) - total
                margin_change = -margin_out
                realized = cash_change - charges_out
        costs.append(
            LegCost(
                kind=leg.kind,
                trade=leg.trade,
                quantity=leg.quantity,
                product=leg.product,
                price=price,
                value=money(leg.quantity * price),
                value_account=value_account,
                charges=charges,
                charges_total=total,
                cash_change=cash_change,
                margin_change=margin_change,
                entry_charges=charges_out,
                entry_value=value_out,
                cost_basis=basis_out,
                realized_pnl=realized,
                trade_id=leg.trade.id if leg.trade is not None else None,
            )
        )

    charges = _merge_charges(costs)
    closing = [c.realized_pnl for c in costs if c.realized_pnl is not None]
    return PlanCost(
        symbol=plan.request.symbol,
        side=plan.request.side,
        quantity=plan.request.quantity,
        price=price,
        currency=quote.currency,
        fx_rate=fx,
        value=sum((c.value for c in costs), ZERO),
        value_account=sum((c.value_account for c in costs), ZERO),
        charges=charges,
        charges_total=sum((c.charges_total for c in costs), ZERO),
        cash_change=sum((c.cash_change for c in costs), ZERO),
        margin_change=sum((c.margin_change for c in costs), ZERO),
        realized_pnl=sum(closing, ZERO) if closing else None,
        legs=costs,
        fifo=plan.fifo,
        note=plan.note,
        broker=broker,
        market=market,
        maker=maker,
    )


def _pricing(side: str, type_: str, limit_price: Decimal | None, quote: Quote) -> tuple[Decimal, bool]:
    """The price an order will be costed at, and whether it will rest as a maker.

    An order that can fill now fills at the current price (a limit is only the worst price you
    accept). One that cannot is costed at its limit price, the best estimate of where it will
    fill, and counts as resting.
    """
    if _reachable(side, type_, limit_price, quote.price):
        return trim8(quote.price), False
    assert limit_price is not None
    return trim8(limit_price), True


def _charges_json(charges: list[Charge]) -> list[dict]:
    # Through the model that serves them, so what is stored always matches what the API returns.
    return [ChargeOut.model_validate(c).model_dump(mode="json") for c in charges]


def leg_out(leg: LegCost) -> OrderLegOut:
    """The one place a leg becomes the shape the API serves and the order stores."""
    return OrderLegOut(
        kind=leg.kind,  # type: ignore[arg-type]
        trade_id=leg.trade_id,
        quantity=leg.quantity,
        product=leg.product,  # type: ignore[arg-type]
        price=leg.price,
        value=leg.value_account,
        charges=[ChargeOut.model_validate(c) for c in leg.charges],
        charges_total=leg.charges_total,
        entry_charges=leg.entry_charges,
        cash_change=leg.cash_change,
        margin_change=leg.margin_change,
        realized_pnl=leg.realized_pnl,
    )


def _legs_json(cost: PlanCost) -> list[dict]:
    return [leg_out(leg).model_dump(mode="json") for leg in cost.legs]


# --- orders ----------------------------------------------------------------------------


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _validate_shape(side: str, type_: str, quantity: Decimal, limit_price: Decimal | None) -> None:
    if side not in OrderSide._value2member_map_:
        raise InvalidOrder("The order side must be 'buy' or 'sell'.")
    if type_ not in OrderType._value2member_map_:
        raise InvalidOrder("The order type must be 'market' or 'limit'.")
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidOrder("Quantity must be greater than zero.")
    if quantity.as_tuple().exponent < -_MAX_QUANTITY_DP:  # type: ignore[operator]
        raise InvalidOrder(f"Quantity can have at most {_MAX_QUANTITY_DP} decimal places.")
    if type_ == OrderType.LIMIT:
        if limit_price is None or not limit_price.is_finite() or limit_price <= 0:
            raise InvalidOrder("A limit order needs a limit price greater than zero.")
    elif limit_price is not None:
        raise InvalidOrder("A market order fills at the current price, so it can't have a limit price.")


def _step_message(market: Market) -> str:
    step = f"{market.quantity_step:f}"
    if market.segment == "crypto":
        return f"Crypto trades in steps of {step}."
    who = "Indian" if market.segment == "india" else "US" if market.code == "US" else market.name
    if market.quantity_step == 1:
        return f"{who} shares trade in whole numbers."
    return f"{who} shares trade in steps of {step}."


def _check_quantity_step(market: Market, quantity: Decimal) -> None:
    """The step an order as a whole trades in. The extra step a short must respect is checked by
    the planner, on the short leg alone."""
    if quantity % market.quantity_step != 0:
        raise InvalidOrder(_step_message(market))


def _fillable(market: Market, quote: Quote) -> bool:
    """Open, and priced by a quote from this session (see `hours.can_fill`)."""
    return hours.can_fill(market, quote.as_of)


def _fx_to_account(provider: MarketDataProvider, instrument_ccy: str, account_ccy: str) -> Decimal:
    # Decimal division gives 28 digits; 8 dp is what we store and what the cash maths uses.
    return trim8(get_fx_rate(provider, instrument_ccy, account_ccy))


def _reachable(side: str, type_: str, limit_price: Decimal | None, price: Decimal) -> bool:
    if type_ == OrderType.MARKET:
        return True
    assert limit_price is not None
    return price <= limit_price if side == OrderSide.BUY else price >= limit_price


def _checked_quote(provider: MarketDataProvider, symbol: str) -> Quote:
    quote = provider.get_quote(symbol)  # MarketDataError propagates: the API maps it
    if quote.type not in TRADABLE_TYPES:
        kind = quote.type
        raise NotTradable(
            f"{quote.name} ({symbol}) is {_article(kind)} {kind}, which can be charted but not traded."
        )
    return quote


def _request(
    db: Session,
    account: Account,
    *,
    symbol: str,
    side: str,
    quantity: Decimal,
    exit_trade_id: int | None,
) -> OrderRequest:
    # Only a plain sell competes with other open sells for the same shares.
    promised = _promised(db, account, symbol) if side == OrderSide.SELL and exit_trade_id is None else ZERO
    return OrderRequest(symbol, side, quantity, exit_trade_id, OrderOrigin.USER, promised)


def preview_order(
    db: Session,
    provider: MarketDataProvider,
    *,
    symbol: str,
    side: str,
    type: str,  # noqa: A002 - matches the Order column and the API field
    quantity: Decimal,
    limit_price: Decimal | None = None,
) -> PlanCost:
    """What `place_order` would charge for the same arguments right now. Writes nothing and
    does not check cash, so a ticket can show the cost of an order you can't afford. It does
    plan the order, so it refuses what placing it would refuse (a short on a market that has
    none, say) with the same sentence."""
    _validate_shape(side, type, quantity, limit_price)
    symbol = symbol.strip().upper()
    account = get_account(db)
    quote = _checked_quote(provider, symbol)
    quantity = trim8(quantity)
    _check_quantity_step(market_data.market_for(symbol, quote.type), quantity)
    request = _request(db, account, symbol=symbol, side=side, quantity=quantity, exit_trade_id=None)
    plan = _plan(db, account, request, quote)
    price, resting = _pricing(side, type, limit_price, quote)
    return plan_cost(provider, account, plan, quote, price=price, order_type=type, resting=resting)


def place_order(
    db: Session,
    provider: MarketDataProvider,
    *,
    symbol: str,
    side: str,
    type: str,  # noqa: A002 - matches the Order column and the API field
    quantity: Decimal,
    limit_price: Decimal | None = None,
) -> Order:
    """Validate, create the order, and fill it at once if it can be. Raises TradingError
    (writing nothing) when the order is not acceptable."""
    return _submit(
        db, provider, symbol=symbol, side=side, type_=type, quantity=quantity,
        limit_price=limit_price, exit_trade_id=None,
    )  # fmt: skip


def _exit_arguments(
    db: Session, account: Account, trade_id: int, quantity: Decimal | None
) -> tuple[Trade, str, Decimal]:
    trade = _get_open_trade(db, account, trade_id)
    side = OrderSide.SELL if trade.direction == TradeDirection.LONG else OrderSide.BUY
    return trade, side, trim8(quantity) if quantity is not None else trade.open_quantity


def exit_trade(
    db: Session, provider: MarketDataProvider, trade_id: int, quantity: Decimal | None = None
) -> Order:
    """Close `quantity` of a trade (all of its open part by default) at the market. Where the
    market pools holdings the oldest lots are what actually close; see `preview_exit`."""
    trade, side, quantity = _exit_arguments(db, get_account(db), trade_id, quantity)
    return _submit(
        db, provider, symbol=trade.symbol, side=side, type_=OrderType.MARKET, quantity=quantity,
        limit_price=None, exit_trade_id=trade.id, origin=OrderOrigin.EXIT,
    )  # fmt: skip


def preview_exit(
    db: Session, provider: MarketDataProvider, trade_id: int, quantity: Decimal | None = None
) -> PlanCost:
    """The payout of `exit_trade` before you commit: the same plan and the same costing."""
    account = get_account(db)
    trade, side, quantity = _exit_arguments(db, account, trade_id, quantity)
    _validate_shape(side, OrderType.MARKET, quantity, None)
    quote = _checked_quote(provider, trade.symbol)
    _check_quantity_step(market_data.market_for(trade.symbol, quote.type), quantity)
    request = OrderRequest(trade.symbol, side, quantity, trade.id)
    plan = _plan(db, account, request, quote)
    price, resting = _pricing(side, OrderType.MARKET, None, quote)
    return plan_cost(
        provider, account, plan, quote, price=price, order_type=OrderType.MARKET, resting=resting
    )


def _submit(
    db: Session,
    provider: MarketDataProvider,
    *,
    symbol: str,
    side: str,
    type_: str,
    quantity: Decimal,
    limit_price: Decimal | None,
    exit_trade_id: int | None,
    origin: str = OrderOrigin.USER,
) -> Order:
    _validate_shape(side, type_, quantity, limit_price)
    symbol = symbol.strip().upper()
    account = get_account(db)
    quote = _checked_quote(provider, symbol)

    quantity = trim8(quantity)
    _check_quantity_step(market_data.market_for(symbol, quote.type), quantity)
    request = _request(db, account, symbol=symbol, side=side, quantity=quantity, exit_trade_id=exit_trade_id)
    plan = _plan(db, account, request, quote)

    # Costed here as well as at the fill so that an order the broker can't take is refused up
    # front, even one that will only rest in the book.
    price, resting = _pricing(side, type_, limit_price, quote)
    cost = plan_cost(provider, account, plan, quote, price=price, order_type=type_, resting=resting)
    fills_now = _reachable(side, type_, limit_price, quote.price) and _fillable(plan.market, quote)
    if not fills_now:
        # An order that waits (a limit not yet reached, or any order while the market is closed)
        # does not reserve cash: it is checked here against the estimated cost, charges and
        # margin included, and again at fill time, when the cash may have been spent.
        _require_funds(account, cost)

    order = Order(
        account_id=account.id,
        symbol=symbol,
        name=quote.name,
        currency=quote.currency,
        side=side,
        type=type_,
        quantity=quantity,
        limit_price=trim8(limit_price) if limit_price is not None else None,
        status=OrderStatus.OPEN,
        charges=[],
        charges_total=ZERO,
        trade_id=exit_trade_id,
        origin=origin,
        cash_change=ZERO,
        legs=[],
        created_at=clock.now(),
    )
    # The order joins the session only after a successful fill (or when it stays open), so a
    # market order that is refused leaves nothing behind.
    if fills_now:
        _fill(db, provider, account, order, quote, resting=False, promised=request.promised)
    db.add(order)
    db.commit()
    return order


def cancel_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFound(f"There is no order with id {order_id}.")
    if order.status != OrderStatus.OPEN:
        raise OrderNotOpen(f"Order {order_id} is already {order.status}, so it can't be cancelled.")
    order.status = OrderStatus.CANCELLED
    db.commit()
    return order


def fill_open_orders(db: Session, provider: MarketDataProvider) -> int:
    """Fill open orders that can: limit orders whose price has been reached, and orders that
    waited for the market to open. Returns how many filled."""
    account = get_account(db)
    open_orders = db.scalars(
        select(Order)
        .where(Order.account_id == account.id, Order.status == OrderStatus.OPEN)
        .order_by(Order.created_at, Order.id)
    ).all()
    filled = 0
    for order in open_orders:
        try:
            quote = provider.get_quote(order.symbol)
        except MarketDataError:
            continue  # no price right now; the order stays open for the next tick
        if not _reachable(order.side, order.type, order.limit_price, quote.price):
            continue
        try:
            if not _fillable(market_data.market_for(order.symbol, quote.type), quote):
                continue  # closed, or the quote is still yesterday's: wait for the next tick
        except TradingError:
            continue
        try:
            _fill(db, provider, account, order, quote, resting=True)
            filled += 1
        except TradingError as exc:
            order.status = OrderStatus.REJECTED
            order.reject_reason = exc.message
        except MarketDataError:
            continue  # the FX rate was unavailable; try again next tick
        db.commit()
    return filled


def _require_funds(account: Account, cost: PlanCost) -> None:
    """Available cash (cash less margin) must cover the order's cash outflow and any margin it
    blocks, and can never end below zero. Checked before anything is changed."""
    available = account.cash - account.margin_used
    need = -cost.cash_change + cost.margin_change
    if need > available:
        ccy = account.currency
        message = f"You need {need:,.2f} {ccy} for this order but only have {available:,.2f} {ccy} in cash"
        if account.margin_used:
            message += f" ({account.cash:,.2f} less {account.margin_used:,.2f} held as margin)"
        message += "."
        if cost.margin_change > 0:
            message += f" {cost.margin_change:,.2f} {ccy} of it would be held as margin against the short."
        raise InsufficientFunds(message)


def _shares_message(symbol: str, held: Decimal, promised: Decimal, wanted: Decimal) -> str:
    free = held - promised
    message = f"You are trying to sell {wanted:f} {symbol} but only {free:f} are free to sell"
    if promised > 0:
        message += f" ({held:f} held, {promised:f} already promised to open sell orders)"
    return message + "."


def _closed_how(order: Order) -> str:
    if order.origin == OrderOrigin.SQUARE_OFF:
        return ClosedHow.SQUARE_OFF
    if order.origin == OrderOrigin.STOP_LOSS:
        return ClosedHow.STOP_LOSS
    if order.origin == OrderOrigin.TARGET:
        return ClosedHow.TARGET
    if order.trade_id is not None:
        return ClosedHow.EXIT
    return ClosedHow.COVER if order.side == OrderSide.BUY else ClosedHow.SELL


def _fill(
    db: Session,
    provider: MarketDataProvider,
    account: Account,
    order: Order,
    quote: Quote,
    *,
    resting: bool,
    promised: Decimal = ZERO,
    note: str | None = None,
) -> None:
    """Fill `order` at the quote's price. Plans and costs it again against the books as they are
    now, checks everything first; only when every guard has passed does it touch the account,
    the trades or the order."""
    # A limit order fills at the current price, not at the limit: the limit is only the worst
    # price the trader accepts, and the market being at or better than it is how limit orders work.
    price = trim8(quote.price)
    request = OrderRequest(order.symbol, order.side, order.quantity, order.trade_id, order.origin, promised)
    plan = _plan(db, account, request, quote)
    cost = plan_cost(provider, account, plan, quote, price=price, order_type=order.type, resting=resting)
    _require_funds(account, cost)

    # All guards passed: mutate.
    now = clock.now()
    db.add(order)
    db.flush()  # the order needs its id before the trades it opens can point back at it
    closed_how = _closed_how(order)
    opened: Trade | None = None
    first_closed: Trade | None = None
    for leg in cost.legs:
        if leg.kind in _OPENING:
            short = leg.kind == LegKind.OPEN_SHORT
            trade = Trade(
                account_id=account.id,
                symbol=order.symbol,
                name=quote.name,
                currency=quote.currency,
                market_code=cost.market.code,
                direction=TradeDirection.SHORT if short else TradeDirection.LONG,
                product=leg.product,
                quantity=leg.quantity,
                open_quantity=leg.quantity,
                entry_price=leg.price,
                entry_fx_rate=cost.fx_rate,
                entry_value=leg.value_account,
                entry_charges=leg.charges_total,
                cost_basis=leg.value_account + leg.charges_total,
                margin_blocked=leg.margin_change,
                financing_paid=ZERO,
                financing_accrued_until=now,
                exit_value=ZERO,
                exit_charges=ZERO,
                realized_pnl=ZERO,
                status=TradeStatus.OPEN,
                opened_at=now,
                opened_by_order_id=order.id,
            )
            db.add(trade)
            db.flush()
            leg.trade_id = trade.id
            opened = opened or trade
        else:
            trade = leg.trade
            assert trade is not None and leg.realized_pnl is not None
            trade.open_quantity -= leg.quantity
            trade.entry_charges -= leg.entry_charges
            trade.entry_value -= leg.entry_value
            trade.cost_basis -= leg.cost_basis
            trade.margin_blocked += leg.margin_change  # negative: released
            trade.exit_value += leg.value_account
            trade.exit_charges += leg.charges_total
            trade.realized_pnl += leg.realized_pnl
            if trade.open_quantity == 0:
                trade.status = TradeStatus.CLOSED
                trade.closed_at = now
                trade.closed_how = closed_how
                # Whatever closed it, a stop or target left behind would have nothing to close.
                trade.stop_price = trade.target_price = trade.protection_expires_at = None
            first_closed = first_closed or trade

    account.cash += cost.cash_change
    account.margin_used += cost.margin_change
    account.realized_pnl += cost.realized_pnl or ZERO

    primary = opened or first_closed
    order.status = OrderStatus.FILLED
    order.fill_price = price
    order.fx_rate = cost.fx_rate
    order.amount = cost.value_account
    order.charges = _charges_json(cost.charges)
    order.charges_total = cost.charges_total
    order.realized_pnl = cost.realized_pnl
    order.cash_change = cost.cash_change
    order.legs = _legs_json(cost)
    if order.trade_id is None and primary is not None:
        order.trade_id = primary.id
    if note is not None:
        order.note = note
    order.filled_at = now


# --- shorts: financing and square-off -----------------------------------------------------


def accrue_financing(db: Session, provider: MarketDataProvider) -> int:
    """Charge borrow (US, a flat yearly rate, daily) or funding (crypto, per eight-hour period)
    on open shorts for the periods completed since each was last charged. Returns how many
    trades were charged.

    It is worked out on the entry value in the account's currency, so it needs no price. The
    charge comes out of cash and out of realized P&L together (and the trade's own), which is
    what keeps realized + unrealized equal to total P&L.
    """
    del provider  # no price is needed; the signature matches the other background steps
    account = get_account(db)
    now = clock.now()
    shorts = db.scalars(
        select(Trade)
        .where(
            Trade.account_id == account.id,
            Trade.status == TradeStatus.OPEN,
            Trade.direction == TradeDirection.SHORT,
        )
        .order_by(Trade.id)
    ).all()
    charged = 0
    for trade in shorts:
        market = market_data.MARKETS.get(trade.market_code)
        rule = market.short_rule if market else None
        if rule is None or rule.borrow_percent_year <= 0:
            continue
        period = timedelta(hours=rule.accrual_hours)
        periods = (now - trade.financing_accrued_until) // period
        if periods < 1:
            continue
        periods_per_year = Decimal(365 * 24) / rule.accrual_hours
        fee = money(trade.entry_value * rule.borrow_percent_year / HUNDRED * periods / periods_per_year)
        if fee <= 0:
            continue  # too small to charge yet; the periods keep adding up until it is a cent
        trade.financing_accrued_until += period * periods
        trade.financing_paid += fee
        trade.realized_pnl -= fee
        account.cash -= fee
        account.realized_pnl -= fee
        charged += 1
    if charged:
        db.commit()
    return charged


def _square_off_note(market: Market, leftover: bool) -> str:
    # In the exchange's own clock: "15:20 IST", never "09:50 UTC".
    status = hours.market_status(market)
    local = clock.now().astimezone(ZoneInfo(status.timezone))
    note = f"Squared off at {local:%H:%M} {local:%Z}"
    return note + (", left open from an earlier session." if leftover else ".")


def square_off_due(db: Session, provider: MarketDataProvider) -> list[Order]:
    """Buy back Indian intraday shorts that must not stay open: those that reach
    `square_off_minutes_before_close` before the close, and straight away any left over from an
    earlier session (at the first fresh quote once the market is open again). Returns the
    orders it placed.

    A cover the account can't pay for is skipped and tried again next tick, so cash still never
    goes below zero.
    """
    account = get_account(db)
    now = clock.now()
    trades = db.scalars(
        select(Trade)
        .where(
            Trade.account_id == account.id,
            Trade.status == TradeStatus.OPEN,
            Trade.product == TradeProduct.INTRADAY,
        )
        .order_by(Trade.opened_at, Trade.id)
    ).all()
    placed: list[Order] = []
    for trade in trades:
        market = market_data.MARKETS.get(trade.market_code)
        rule = market.short_rule if market else None
        if market is None or rule is None or rule.square_off_minutes_before_close is None:
            continue
        status = hours.market_status(market)
        if status.state != "open":
            continue
        leftover = status.session_open is not None and trade.opened_at < status.session_open
        near_close = status.next_close is not None and now >= status.next_close - timedelta(
            minutes=rule.square_off_minutes_before_close
        )
        if not (leftover or near_close):
            continue
        try:
            quote = provider.get_quote(trade.symbol)
        except MarketDataError:
            continue
        if not hours.can_fill(market, quote.as_of):
            continue  # still yesterday's price; wait for a fresh one
        side = OrderSide.SELL if trade.direction == TradeDirection.LONG else OrderSide.BUY
        order = Order(
            account_id=account.id,
            symbol=trade.symbol,
            name=trade.name,
            currency=trade.currency,
            side=side,
            type=OrderType.MARKET,
            quantity=trade.open_quantity,
            status=OrderStatus.OPEN,
            charges=[],
            charges_total=ZERO,
            trade_id=trade.id,
            origin=OrderOrigin.SQUARE_OFF,
            cash_change=ZERO,
            legs=[],
            created_at=now,
        )
        try:
            _fill(db, provider, account, order, quote, resting=False, note=_square_off_note(market, leftover))
        except (TradingError, MarketDataError) as exc:
            db.rollback()
            logger.warning("Could not square off trade %d (%s): %s", trade.id, trade.symbol, exc)
            continue
        db.commit()
        placed.append(order)
        logger.info("Trade %d (%s): %s", trade.id, trade.symbol, order.note)
    return placed


# --- stop-loss and target --------------------------------------------------------------


@dataclass
class ProtectionOutcome:
    """What closing a trade's whole open part at `price` would leave you with, every charge
    counted. Worked out by `plan_cost` like any exit, so it is what the exit would really do."""

    price: Decimal  # instrument currency
    exit_value: Decimal  # account currency, before charges
    charges_total: Decimal
    realized_pnl: Decimal  # the part you are closing, entry charges included
    cash_change: Decimal


@dataclass
class ProtectionPreview:
    current_price: Decimal
    currency: str
    errors: dict[str, str]  # "stop_price" / "target_price" -> why that price is refused
    stop_outcome: ProtectionOutcome | None
    target_outcome: ProtectionOutcome | None


_CURRENCY_SIGNS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _price_text(price: Decimal, currency: str) -> str:
    sign = _CURRENCY_SIGNS.get(currency)
    text = f"{price:,.2f}" if price >= 1 else f"{price:,.8f}".rstrip("0").rstrip(".")
    return f"{sign}{text}" if sign else f"{text} {currency}"


def _protection_problems(
    trade: Trade, market: Market, current: Decimal, stop: Decimal | None, target: Decimal | None
) -> dict[str, str]:
    """Why each given price is refused, by field. Every price is judged against the current one:
    for a long the stop sits below and the target above, for a short the other way round.

    There is deliberately no check that the stop and target aren't crossed. Each on its own side
    of the same current price already makes that impossible, so such a check could never fire.
    """
    long = trade.direction == TradeDirection.LONG
    step = Decimal("0.00000001") if market.segment == "crypto" else Decimal("0.01")
    now_text = _price_text(current, trade.currency)
    problems: dict[str, str] = {}
    for field, label, price in (("stop_price", "stop-loss", stop), ("target_price", "target", target)):
        if price is None:
            continue
        if not price.is_finite() or price <= 0:
            problems[field] = f"The {label} must be a price greater than zero."
            continue
        if price % step != 0:
            places = -step.as_tuple().exponent  # type: ignore[operator]
            problems[field] = (
                f"{market.name} prices move in steps of {step:f}, so the {label} can have at most "
                f"{places} decimal places."
            )
            continue
        is_stop = field == "stop_price"
        below = is_stop == long  # a long's stop and a short's target go below
        if below and price >= current:
            reason = "it's there to limit a fall" if is_stop else "a short profits when the price falls"
            problems[field] = (
                f"For a {trade.direction} trade the {label} must be below the current price "
                f"({now_text}) — {reason}."
            )
        elif not below and price <= current:
            reason = "it's there to limit a rise" if is_stop else "a long profits when the price rises"
            problems[field] = (
                f"For a {trade.direction} trade the {label} must be above the current price "
                f"({now_text}) — {reason}."
            )
    return problems


def _protection_outcome(
    db: Session, provider: MarketDataProvider, account: Account, trade: Trade, quote: Quote, price: Decimal
) -> ProtectionOutcome:
    side = OrderSide.SELL if trade.direction == TradeDirection.LONG else OrderSide.BUY
    request = OrderRequest(trade.symbol, side, trade.open_quantity, trade.id, OrderOrigin.STOP_LOSS)
    plan = _plan(db, account, request, quote)
    cost = plan_cost(provider, account, plan, quote, price=price, order_type=OrderType.MARKET)
    return ProtectionOutcome(
        price=cost.price,
        exit_value=cost.value_account,
        charges_total=cost.charges_total,
        realized_pnl=cost.realized_pnl or ZERO,
        cash_change=cost.cash_change,
    )


def _open_trade_for_protection(db: Session, account: Account, trade_id: int) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None or trade.account_id != account.id:
        raise TradeNotFound(f"There is no trade with id {trade_id}.")
    if trade.status != TradeStatus.OPEN:
        raise TradeNotOpen(f"Trade {trade_id} is already closed, so it can't have a stop-loss or target.")
    return trade


def preview_protection(
    db: Session,
    provider: MarketDataProvider,
    trade_id: int,
    stop_price: Decimal | None,
    target_price: Decimal | None,
) -> ProtectionPreview:
    """What `set_protection` would say and what each price would leave you with. Saves nothing."""
    account = get_account(db)
    trade = _open_trade_for_protection(db, account, trade_id)
    quote = _checked_quote(provider, trade.symbol)
    market = market_data.market_for(trade.symbol, quote.type)
    errors = _protection_problems(trade, market, quote.price, stop_price, target_price)
    outcomes: dict[str, ProtectionOutcome | None] = {"stop_price": None, "target_price": None}
    for field, price in (("stop_price", stop_price), ("target_price", target_price)):
        if price is not None and field not in errors:
            outcomes[field] = _protection_outcome(db, provider, account, trade, quote, price)
    return ProtectionPreview(
        trim8(quote.price), quote.currency, errors, outcomes["stop_price"], outcomes["target_price"]
    )


def set_protection(
    db: Session,
    provider: MarketDataProvider,
    trade_id: int,
    stop_price: Decimal | None,
    target_price: Decimal | None,
) -> TradeView:
    """Set (or, with None, clear) a trade's stop-loss and target, each checked against the
    current price. Both None clears protection. A year's expiry, like a GTT."""
    account = get_account(db)
    trade = _open_trade_for_protection(db, account, trade_id)
    quote = _checked_quote(provider, trade.symbol)
    market = market_data.market_for(trade.symbol, quote.type)
    problems = _protection_problems(trade, market, quote.price, stop_price, target_price)
    if problems:
        raise ProtectionInvalid(problems)
    trade.stop_price = trim8(stop_price) if stop_price is not None else None
    trade.target_price = trim8(target_price) if target_price is not None else None
    if stop_price is None and target_price is None:
        trade.protection_expires_at = None
    else:
        trade.protection_expires_at = clock.now() + timedelta(days=PROTECTION_DAYS)
    db.commit()
    return get_trade_view(db, provider, trade.id)


def _protection_fires(trade: Trade, price: Decimal) -> str | None:
    """Which of the two the price has reached, if either. The stop is asked first: when a gap
    takes the price through both, a real broker's stop is what is hit first, so you take the loss."""
    long = trade.direction == TradeDirection.LONG
    if trade.stop_price is not None and (price <= trade.stop_price if long else price >= trade.stop_price):
        return OrderOrigin.STOP_LOSS
    target = trade.target_price
    if target is not None and (price >= target if long else price <= target):
        return OrderOrigin.TARGET
    return None


def trigger_protected_trades(db: Session, provider: MarketDataProvider) -> int:
    """Close, at the market, every open trade whose stop-loss or target the price has reached.
    Returns how many closed.

    Watched only while the market is open and only against a quote from the current session,
    like any fill. The whole open part closes at the quote's price, not at the stop or target
    price: a gap down to 1,100 through a stop at 1,200 gets out at 1,100. It goes through the
    same plan and costing as the Exit button. Firing closes the trade, which clears both prices,
    so one firing ends the other. A trade that can't be closed now (no cash to cover a short, say)
    is tried again next tick, and one failing never stops the others.
    """
    account = get_account(db)
    now = clock.now()
    trades = db.scalars(
        select(Trade)
        .where(
            Trade.account_id == account.id,
            Trade.status == TradeStatus.OPEN,
            or_(Trade.stop_price.is_not(None), Trade.target_price.is_not(None)),
        )
        .order_by(Trade.id)
    ).all()
    closed = 0
    for trade in trades:
        if trade.protection_expires_at is not None and now >= trade.protection_expires_at:
            trade.stop_price = trade.target_price = trade.protection_expires_at = None
            db.commit()
            continue
        market = market_data.MARKETS.get(trade.market_code)
        if market is None:
            continue
        try:
            quote = provider.get_quote(trade.symbol)
        except MarketDataError:
            continue
        if not hours.can_fill(market, quote.as_of):
            continue  # closed, or still yesterday's price: wait for a fresh one
        origin = _protection_fires(trade, quote.price)
        if origin is None:
            continue
        label = "Stop-loss" if origin == OrderOrigin.STOP_LOSS else "Target"
        set_price = trade.stop_price if origin == OrderOrigin.STOP_LOSS else trade.target_price
        assert set_price is not None
        note = (
            f"{label} of {_price_text(set_price, trade.currency)} reached; "
            f"sold at the market price of {_price_text(trim8(quote.price), trade.currency)}."
            if trade.direction == TradeDirection.LONG
            else f"{label} of {_price_text(set_price, trade.currency)} reached; "
            f"bought back at the market price of {_price_text(trim8(quote.price), trade.currency)}."
        )
        side = OrderSide.SELL if trade.direction == TradeDirection.LONG else OrderSide.BUY
        order = Order(
            account_id=account.id,
            symbol=trade.symbol,
            name=trade.name,
            currency=trade.currency,
            side=side,
            type=OrderType.MARKET,
            quantity=trade.open_quantity,
            status=OrderStatus.OPEN,
            charges=[],
            charges_total=ZERO,
            trade_id=trade.id,
            origin=origin,
            cash_change=ZERO,
            legs=[],
            created_at=now,
        )
        try:
            _fill(db, provider, account, order, quote, resting=False, note=note)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one trade failing must not stop the others
            db.rollback()
            logger.warning(
                "Could not fire %s on trade %d (%s): %s", label.lower(), trade.id, trade.symbol, exc
            )
            continue
        closed += 1
        logger.info("Trade %d (%s): %s", trade.id, trade.symbol, note)
    return closed


# --- portfolio -------------------------------------------------------------------------


@dataclass
class TradeView:
    """A trade with its live figures. Anything not set here is read from the trade itself, so the
    API model can serve both without a hundred copied fields."""

    trade: Trade
    entry_charges_paid: Decimal
    lot_exits: str
    last_price: Decimal | None = None
    market_value: Decimal | None = None  # a short's: what covering would cost
    unrealized_pnl: Decimal | None = None
    unrealized_pct: Decimal | None = None
    price_unavailable: bool = False
    stop_outcome: ProtectionOutcome | None = None
    target_outcome: ProtectionOutcome | None = None

    def __getattr__(self, name: str):
        if name == "trade":  # not set yet (copying, unpickling): don't recurse
            raise AttributeError(name)
        return getattr(self.trade, name)


@dataclass
class HoldingView:
    symbol: str
    name: str
    currency: str
    direction: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    margin_blocked: Decimal
    last_price: Decimal | None
    fx_rate: Decimal | None
    market_value: Decimal  # account currency
    unrealized_pnl: Decimal
    unrealized_pct: Decimal | None
    price_unavailable: bool
    break_even_price: Decimal | None  # instrument currency; None if it can't be worked out
    trade_count: int


@dataclass
class ChargesPaid:
    total: Decimal
    by_category: dict[str, Decimal]


@dataclass
class Portfolio:
    currency: str
    cash: Decimal
    margin_used: Decimal
    available_cash: Decimal
    starting_cash: Decimal
    invested: Decimal
    market_value: Decimal
    short_value: Decimal
    total_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    financing_paid: Decimal
    charges_paid: ChargesPaid
    holdings: list[HoldingView]
    trades: list[TradeView]


def _charges_paid(db: Session, account: Account) -> ChargesPaid:
    """What filled orders have cost, by category. Summed in Python: the amounts are JSON text."""
    by_category = dict.fromkeys(CATEGORIES, ZERO)
    filled = db.scalars(
        select(Order).where(Order.account_id == account.id, Order.status == OrderStatus.FILLED)
    )
    for order in filled:
        for charge in order.charges:
            by_category[charge["category"]] += Decimal(charge["amount"])
    return ChargesPaid(sum(by_category.values(), ZERO), by_category)


def _entry_charges_paid(db: Session, trades: list[Trade]) -> dict[int, Decimal]:
    """What each trade paid to get in, read from the legs of the order that opened it: that
    record never shrinks, unlike the trade's own `entry_charges`. A trade carried over from the
    old positions table has no such record, so it reports what it holds (nothing was recorded)."""
    order_ids = {t.opened_by_order_id for t in trades if t.opened_by_order_id is not None}
    found = db.scalars(select(Order).where(Order.id.in_(list(order_ids)))) if order_ids else []
    orders = {o.id: o for o in found}
    paid: dict[int, Decimal] = {}
    for trade in trades:
        paid[trade.id] = trade.entry_charges
        order = orders.get(trade.opened_by_order_id) if trade.opened_by_order_id is not None else None
        for leg in order.legs if order else []:
            if leg["trade_id"] == trade.id and leg["kind"] in _OPENING:
                paid[trade.id] = Decimal(leg["charges_total"])
    return paid


def _lot_exits(trade: Trade) -> str:
    market = market_data.MARKETS.get(trade.market_code)
    return market.lot_exits if market else "fifo"


def _value_trade(trade: Trade, quote: Quote | None, fx: Decimal | None) -> TradeView:
    """Mark one open trade. The figures here are what the totals add up, so they can't drift.

    Without a price or rate it is valued at cost rather than hiding it or inventing a loss:
    a long at its cost basis, a short at the cost of covering that leaves unrealized at zero.
    """
    long = trade.direction == TradeDirection.LONG
    view = TradeView(trade, ZERO, _lot_exits(trade))
    if quote is None or fx is None:
        view.price_unavailable = True
        view.market_value = trade.cost_basis if long else trade.entry_value - trade.entry_charges
        view.unrealized_pnl = ZERO
        return view
    value = money(trade.open_quantity * quote.price * fx)
    view.last_price = trim8(quote.price)
    view.market_value = value
    # A long is worth value against what it cost (entry charges included). A short took in its
    # entry value and owes value to buy back; the entry charges are already spent.
    short_pnl = trade.entry_value - value - trade.entry_charges
    view.unrealized_pnl = value - trade.cost_basis if long else short_pnl
    if trade.cost_basis:
        view.unrealized_pct = (view.unrealized_pnl / trade.cost_basis * 100).quantize(Decimal("0.01"))
    return view


def _attach_outcomes(
    db: Session, provider: MarketDataProvider, account: Account, view: TradeView, quote: Quote | None
) -> None:
    """What each of the trade's prices would leave you with. Left empty if it can't be worked
    out right now (no price, or the broker no longer offers the market)."""
    trade = view.trade
    if quote is None or view.price_unavailable:
        return
    for name, price in (("stop_outcome", trade.stop_price), ("target_outcome", trade.target_price)):
        if price is None:
            continue
        try:
            setattr(view, name, _protection_outcome(db, provider, account, trade, quote, price))
        except (TradingError, MarketDataError):
            pass


def _pct(amount: Decimal, basis: Decimal) -> Decimal | None:
    return (amount / basis * 100).quantize(Decimal("0.01")) if basis else None


def _break_even(
    account: Account, trades: list[Trade], quote: Quote, fx: Decimal, quantity: Decimal
) -> Decimal | None:
    """Where closing the pooled trades now would return what they cost, or None if their costs
    can't be worked out (the broker in Settings no longer offers the market, say)."""
    first = trades[0]
    try:
        market = market_data.market_for(first.symbol, quote.type)
        broker = _broker_for(account, market)
        common = dict(
            instrument_type=quote.type,
            instrument_currency=quote.currency,
            account_currency=account.currency,
            fx_rate=fx,
            product=first.product,
        )
        if first.direction == TradeDirection.LONG:
            return break_even_price(
                market, broker, quantity=quantity,
                cost_basis=sum((t.cost_basis for t in trades), ZERO), **common,
            )  # fmt: skip
        return break_even_cover_price(
            market, broker, quantity=quantity,
            entry_value=sum((t.entry_value for t in trades), ZERO),
            entry_charges=sum((t.entry_charges for t in trades), ZERO), **common,
        )  # fmt: skip
    except (TradingError, ValueError):
        return None


def get_portfolio(db: Session, provider: MarketDataProvider) -> Portfolio:
    account = get_account(db)
    trades = _open_trades_of_account(db, account)
    quotes = get_quotes(provider, [t.symbol for t in trades])

    fx_cache: dict[str, Decimal | None] = {}

    def fx_for(currency: str) -> Decimal | None:
        if currency not in fx_cache:
            try:
                fx_cache[currency] = _fx_to_account(provider, currency, account.currency)
            except MarketDataError:
                fx_cache[currency] = None
        return fx_cache[currency]

    paid = _entry_charges_paid(db, trades)
    views: list[TradeView] = []
    for t in trades:
        quote = quotes.get(t.symbol)
        view = _value_trade(t, quote, fx_for(t.currency) if quote else None)
        view.entry_charges_paid = paid[t.id]
        _attach_outcomes(db, provider, account, view, quote)
        views.append(view)

    holdings: list[HoldingView] = []
    groups: dict[tuple[str, str], list[TradeView]] = {}
    for v in views:
        groups.setdefault((v.trade.symbol, v.trade.direction), []).append(v)
    for (symbol, direction), members in sorted(groups.items()):
        ts = [m.trade for m in members]
        quantity = sum((t.open_quantity for t in ts), ZERO)
        cost_basis = sum((t.cost_basis for t in ts), ZERO)
        unrealized = sum((m.unrealized_pnl or ZERO for m in members), ZERO)
        quote = quotes.get(symbol)
        fx = fx_for(ts[0].currency) if quote else None
        unavailable = any(m.price_unavailable for m in members)
        holdings.append(
            HoldingView(
                symbol=symbol,
                name=ts[0].name,
                currency=ts[0].currency,
                direction=direction,
                quantity=quantity,
                avg_price=trim8(sum((t.open_quantity * t.entry_price for t in ts), ZERO) / quantity),
                cost_basis=cost_basis,
                margin_blocked=sum((t.margin_blocked for t in ts), ZERO),
                last_price=None if unavailable or quote is None else trim8(quote.price),
                fx_rate=None if unavailable else fx,
                market_value=sum((m.market_value or ZERO for m in members), ZERO),
                unrealized_pnl=unrealized,
                unrealized_pct=_pct(unrealized, cost_basis),
                price_unavailable=unavailable,
                break_even_price=None
                if unavailable or quote is None or fx is None
                else _break_even(account, ts, quote, fx, quantity),
                trade_count=len(ts),
            )
        )

    longs = [v for v in views if v.trade.direction == TradeDirection.LONG]
    shorts = [v for v in views if v.trade.direction == TradeDirection.SHORT]
    invested = sum((v.trade.cost_basis for v in longs), ZERO)
    market_value = sum((v.market_value or ZERO for v in longs), ZERO)
    short_value = sum((v.trade.entry_value - (v.market_value or ZERO) for v in shorts), ZERO)
    unrealized_total = sum((v.unrealized_pnl or ZERO for v in views), ZERO)
    total_value = account.cash + market_value + short_value
    financing = sum(
        (t.financing_paid for t in db.scalars(select(Trade).where(Trade.account_id == account.id))), ZERO
    )
    # realized + unrealized == total_value - starting_cash holds with charges and with shorts
    # open, because every move of cash is matched by a move in what is counted against it:
    #   buy        cash -(value + charges), a long's cost_basis +(value + charges)
    #   sell       cash +(value - charges), cost_basis -cost_out, realized (value - charges - cost_out)
    #   short      cash -charges, entry_charges +charges (the proceeds are not paid out)
    #   cover      cash +(entry value - cover value - charges), entry_charges -allocated, realized
    #              (entry value - cover value - charges - allocated)
    #   financing  cash -fee, realized -fee
    # so realized_pnl = cash - starting_cash + sum(open longs' cost_basis) + sum(open shorts'
    # entry_charges) always, whatever the prices are. A long's unrealized is value - cost_basis, a
    # short's is entry value - value - entry_charges, and total value is cash + long values +
    # sum(short entry value - value): the difference of the two sides is that same identity.
    return Portfolio(
        currency=account.currency,
        cash=account.cash,
        margin_used=account.margin_used,
        available_cash=account.cash - account.margin_used,
        starting_cash=account.starting_cash,
        invested=invested,
        market_value=market_value,
        short_value=short_value,
        total_value=total_value,
        realized_pnl=account.realized_pnl,
        unrealized_pnl=unrealized_total,
        total_pnl=total_value - account.starting_cash,
        financing_paid=financing,
        charges_paid=_charges_paid(db, account),
        holdings=holdings,
        trades=views,
    )


def _open_trades_of_account(db: Session, account: Account) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade)
            .where(Trade.account_id == account.id, Trade.status == TradeStatus.OPEN)
            .order_by(Trade.opened_at, Trade.id)
        )
    )


def list_trades(
    db: Session,
    provider: MarketDataProvider,
    *,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 100,
) -> list[TradeView]:
    """Trades, newest first. Open ones carry live figures; closed ones report what they paid
    from the order records, so entry charges never read zero."""
    account = get_account(db)
    query = select(Trade).where(Trade.account_id == account.id)
    if status is not None:
        query = query.where(Trade.status == status)
    if symbol is not None:
        query = query.where(Trade.symbol == symbol)
    trades = list(db.scalars(query.order_by(Trade.id.desc()).limit(limit)))
    return _views_of(db, provider, account, trades)


def get_trade_view(db: Session, provider: MarketDataProvider, trade_id: int) -> TradeView:
    account = get_account(db)
    trade = db.get(Trade, trade_id)
    if trade is None or trade.account_id != account.id:
        raise TradeNotFound(f"There is no trade with id {trade_id}.")
    return _views_of(db, provider, account, [trade])[0]


def _views_of(
    db: Session, provider: MarketDataProvider, account: Account, trades: list[Trade]
) -> list[TradeView]:
    paid = _entry_charges_paid(db, trades)
    quotes = get_quotes(provider, [t.symbol for t in trades if t.status == TradeStatus.OPEN])
    fx_cache: dict[str, Decimal | None] = {}
    views: list[TradeView] = []
    for t in trades:
        if t.status == TradeStatus.OPEN:
            quote = quotes.get(t.symbol)
            if quote is not None and t.currency not in fx_cache:
                try:
                    fx_cache[t.currency] = _fx_to_account(provider, t.currency, account.currency)
                except MarketDataError:
                    fx_cache[t.currency] = None
            view = _value_trade(t, quote, fx_cache.get(t.currency) if quote else None)
            _attach_outcomes(db, provider, account, view, quote)
        else:
            view = TradeView(t, ZERO, _lot_exits(t))
        view.entry_charges_paid = paid[t.id]
        views.append(view)
    return views


# --- payouts ---------------------------------------------------------------------------


def _sum_lines(lines: list[ChargeOut]) -> list[ChargeOut]:
    """Lines with the same name added together, in the order first seen."""
    merged: dict[tuple[str, str], ChargeOut] = {}
    for line in lines:
        key = (line.category, line.name)
        if key in merged:
            have = merged[key]
            merged[key] = have.model_copy(
                update={
                    "amount": have.amount + line.amount,
                    "native_amount": have.native_amount + line.native_amount,
                }
            )
        else:
            merged[key] = line
    return list(merged.values())


def get_payouts(db: Session, *, limit: int = 500) -> PayoutsOut:
    """Every closed trade with what it brought in and what it paid at both ends, line by line.

    The lines are read from the legs of the filled orders (an immutable record), not from the
    trade, whose entry fields shrink as it is exited: a fully closed trade would otherwise report
    zero entry charges. A trade carried over from the old positions table has no opening order,
    so its entry lines are empty and its entry value is rebuilt from its quantity and price.
    """
    account = get_account(db)
    closed = list(
        db.scalars(
            select(Trade)
            .where(Trade.account_id == account.id, Trade.status == TradeStatus.CLOSED)
            .order_by(Trade.closed_at.desc(), Trade.id.desc())
        )
    )
    entry_legs: dict[int, OrderLegOut] = {}
    exit_lines: dict[int, list[ChargeOut]] = {}
    ids = {t.id for t in closed}
    if ids:
        filled = db.scalars(
            select(Order)
            .where(Order.account_id == account.id, Order.status == OrderStatus.FILLED)
            .order_by(Order.id)
        )
        for order in filled:
            for raw in order.legs:
                leg = OrderLegOut.model_validate(raw)
                if leg.trade_id not in ids:
                    continue
                assert leg.trade_id is not None
                if leg.kind in _OPENING:
                    entry_legs[leg.trade_id] = leg
                else:
                    exit_lines.setdefault(leg.trade_id, []).extend(leg.charges)

    payouts: list[PayoutOut] = []
    for t in closed:
        entry = entry_legs.get(t.id)
        entry_value = entry.value if entry else money(t.quantity * t.entry_price * t.entry_fx_rate)
        short = t.direction == TradeDirection.SHORT
        payouts.append(
            PayoutOut(
                trade_id=t.id,
                symbol=t.symbol,
                name=t.name,
                currency=t.currency,
                market_code=t.market_code,
                direction=t.direction,  # type: ignore[arg-type]
                product=t.product,  # type: ignore[arg-type]
                quantity=t.quantity,
                opened_at=t.opened_at,
                closed_at=t.closed_at or t.opened_at,
                closed_how=t.closed_how or ClosedHow.EXIT,  # type: ignore[arg-type]
                entry_price=t.entry_price,
                entry_value=entry_value,
                brought_in=entry_value - t.exit_value if short else t.exit_value,
                exit_value=t.exit_value,
                entry_charge_lines=list(entry.charges) if entry else [],
                entry_charges_total=entry.charges_total if entry else ZERO,
                exit_charge_lines=_sum_lines(exit_lines.get(t.id, [])),
                exit_charges_total=t.exit_charges,
                financing_paid=t.financing_paid,
                realized_pnl=t.realized_pnl,
            )
        )
    totals = PayoutTotalsOut(
        trades_closed=len(payouts),
        brought_in=sum((p.brought_in for p in payouts), ZERO),
        charges=sum((p.entry_charges_total + p.exit_charges_total for p in payouts), ZERO),
        financing=sum((p.financing_paid for p in payouts), ZERO),
        net_profit=sum((p.realized_pnl for p in payouts), ZERO),
    )
    return PayoutsOut(currency=account.currency, totals=totals, payouts=payouts[:limit])
