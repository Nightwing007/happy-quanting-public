"""Which badges a user has earned, computed from their data and nothing else.

Every condition is one small function named after its badge, taking the user's `Facts` and
returning a bool. Trading badges read only the user's live accounts (sims and backtests can be
replayed until lucky), except where a badge says otherwise (Volcano, Glacier, Mind). The
evaluator writes nothing; `award.py` turns its answer into rows.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.badges.catalog import BADGES, CHAMPION, ELITE_FOUR, REGIONS, region_badges
from app.models import (
    Account,
    AccountKind,
    AlgoListing,
    Backtest,
    BacktestStatus,
    ClosedHow,
    ListingPerformance,
    ListingStatus,
    ListingVersion,
    Order,
    OrderStatus,
    PerformanceStatus,
    SimSession,
    SimStatus,
    Subscription,
    Trade,
    TradeDirection,
    TradeProduct,
    TradeStatus,
)
from app.trading import hours, markets
from app.trading.errors import UnsupportedMarket

ZERO = Decimal(0)
# Closed by you, as opposed to the broker (square_off) or a stop-loss or target.
CLOSED_BY_YOU = frozenset({ClosedHow.EXIT, ClosedHow.SELL, ClosedHow.COVER})
LONG_HOLD = timedelta(days=30)
_CRYPTO_QUOTES = ("-USD", "-USDT", "-EUR", "-GBP", "-INR", "-BTC")
_CRYPTO_CLOSED_MARKETS = ("NSE", "US", "LSE")


def group_of_code(market_code: str) -> str:
    """The market group a market belongs to: india, us, crypto, or global (everything else)."""
    if market_code in ("NSE", "BSE"):
        return "india"
    if market_code == "US":
        return "us"
    if market_code == "CRYPTO":
        return "crypto"
    return "global"


def market_of_symbol(symbol: str) -> markets.Market | None:
    """The market of a Yahoo symbol, None for one we don't model. Crypto pairs are told by their
    quote currency suffix (the instrument type isn't stored on orders or sessions)."""
    kind = "crypto" if symbol.upper().endswith(_CRYPTO_QUOTES) else "equity"
    try:
        return markets.market_for(symbol, kind)
    except UnsupportedMarket:
        return None


def group_of_symbol(symbol: str) -> str:
    market = market_of_symbol(symbol)
    return "global" if market is None else group_of_code(market.code)


class Facts:
    """What the conditions read. Loaded once per evaluation; the sim, backtest and marketplace
    reads are lazy, so a user who never made one costs no query."""

    def __init__(self, db: Session, user_id: int, now: datetime) -> None:
        self.db, self.user_id, self.now = db, user_id, now
        accounts = list(
            db.scalars(select(Account).where(Account.kind == AccountKind.LIVE, Account.user_id == user_id))
        )
        ids = [a.id for a in accounts]
        self.starting_cash = sum((a.starting_cash for a in accounts), ZERO)
        self.trades: list[Trade] = (
            list(db.scalars(select(Trade).where(Trade.account_id.in_(ids)).order_by(Trade.id))) if ids else []
        )
        self.orders: list[Order] = (
            list(db.scalars(select(Order).where(Order.account_id.in_(ids)).order_by(Order.id))) if ids else []
        )
        self.by_group: dict[str, list[Trade]] = {}
        for trade in self.trades:
            self.by_group.setdefault(group_of_code(trade.market_code), []).append(trade)

    def closed(self, group: str) -> list[Trade]:
        """The group's closed trades, oldest close first."""
        rows = [t for t in self.by_group.get(group, []) if t.status == TradeStatus.CLOSED and t.closed_at]
        return sorted(rows, key=lambda t: (t.closed_at, t.id))

    @cached_property
    def finished_sims(self) -> list[SimSession]:
        return list(
            self.db.scalars(
                select(SimSession).where(
                    SimSession.owner_user_id == self.user_id, SimSession.status == SimStatus.FINISHED
                )
            )
        )

    @cached_property
    def done_backtests(self) -> list[Backtest]:
        return list(
            self.db.scalars(
                select(Backtest).where(
                    Backtest.owner_user_id == self.user_id, Backtest.status == BacktestStatus.DONE
                )
            )
        )

    @cached_property
    def listings(self) -> list[AlgoListing]:
        """Listings that have been published (and perhaps retired since), never drafts."""
        return list(
            self.db.scalars(
                select(AlgoListing).where(
                    AlgoListing.owner_user_id == self.user_id,
                    AlgoListing.status.in_([ListingStatus.PUBLISHED, ListingStatus.RETIRED]),
                )
            )
        )

    @cached_property
    def done_windows(self) -> dict[int, list[ListingPerformance]]:
        out: dict[int, list[ListingPerformance]] = {}
        ids = [x.id for x in self.listings]
        rows = (
            self.db.scalars(
                select(ListingPerformance).where(
                    ListingPerformance.listing_id.in_(ids),
                    ListingPerformance.status == PerformanceStatus.DONE,
                )
            )
            if ids
            else []
        )
        for row in rows:
            out.setdefault(row.listing_id, []).append(row)
        return out

    @cached_property
    def subscriptions(self) -> list[Subscription]:
        """Subscriptions to the user's listings by other people (subscribing to your own listing
        to farm a badge doesn't count)."""
        ids = [x.id for x in self.listings]
        if not ids:
            return []
        return list(
            self.db.scalars(
                select(Subscription).where(
                    Subscription.listing_id.in_(ids), Subscription.subscriber_user_id != self.user_id
                )
            )
        )


# --- shared conditions -------------------------------------------------------------------


def _traded(f: Facts, group: str) -> bool:
    return bool(f.by_group.get(group))


def _protected(trade: Trade) -> bool:
    """A stop-loss or target was set. The target alone leaves no trace once a trade closes by
    hand, so a closed target-only trade counts only if the target is what closed it."""
    return (
        trade.had_stop
        or trade.target_price is not None
        or trade.closed_how in (ClosedHow.STOP_LOSS, ClosedHow.TARGET)
    )


def _protection_used(f: Facts, group: str) -> bool:
    return any(_protected(t) for t in f.by_group.get(group, []))


def _distinct_symbols(f: Facts, group: str, count: int) -> bool:
    return len({t.symbol for t in f.by_group.get(group, [])}) >= count


def _protected_streak(f: Facts, group: str, count: int) -> bool:
    """`count` closed trades in a row (by close), every one with a stop-loss set. Counted as a
    run so one early unprotected trade doesn't shut the badge for good."""
    run = 0
    for trade in f.closed(group):
        run = run + 1 if trade.had_stop else 0
        if run >= count:
            return True
    return False


def _held(f: Facts, group: str, delivery_only: bool = False) -> bool:
    for t in f.by_group.get(group, []):
        if delivery_only and t.product != TradeProduct.DELIVERY:
            continue
        if (t.closed_at or f.now) - t.opened_at >= LONG_HOLD:
            return True
    return False


def max_drawdown_pct(trades: list[Trade], starting_cash: Decimal) -> Decimal:
    """The largest peak-to-trough fall of cumulative realized P&L over `trades` (oldest close
    first), as a percent of starting cash. The peak starts at zero, before the first trade."""
    total = peak = worst = ZERO
    for trade in trades:
        total += trade.realized_pnl
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst * 100 / starting_cash if starting_cash > 0 else Decimal(100)


def _capstone(f: Facts, group: str, limit_pct: int) -> bool:
    rows = f.closed(group)
    if len(rows) < 20 or sum((t.realized_pnl for t in rows), ZERO) <= 0:
        return False
    return max_drawdown_pct(rows, f.starting_cash) < limit_pct


def _own_close(t: Trade) -> bool:
    return t.closed_how in CLOSED_BY_YOU


def _short_closed_by_you(f: Facts, group: str, product: str | None, paid_financing: bool) -> bool:
    for t in f.by_group.get(group, []):
        if t.direction != TradeDirection.SHORT or not _own_close(t):
            continue
        if product is not None and t.product != product:
            continue
        if paid_financing and t.financing_paid <= 0:
            continue
        return True
    return False


def _sim_day(f: Facts, group: str) -> bool:
    return any(group_of_symbol(sym) == group for s in f.finished_sims for sym in s.symbols)


def _pays_tax(order: Order) -> bool:
    lines = list(order.charges or [])
    for leg in order.legs or []:
        lines.extend(leg.get("charges", []))
    return any(line.get("category") == "tax" for line in lines)


# --- Kanto: India ------------------------------------------------------------------------


def boulder(f: Facts) -> bool:
    return _traded(f, "india")


def cascade(f: Facts) -> bool:
    return _protection_used(f, "india")


def thunder(f: Facts) -> bool:
    return _short_closed_by_you(f, "india", TradeProduct.INTRADAY, paid_financing=False)


def rainbow(f: Facts) -> bool:
    return _distinct_symbols(f, "india", 5)


def soul(f: Facts) -> bool:
    return _protected_streak(f, "india", 10)


def marsh(f: Facts) -> bool:
    return _held(f, "india", delivery_only=True)


def volcano(f: Facts) -> bool:
    return _sim_day(f, "india")


def earth(f: Facts) -> bool:
    return _capstone(f, "india", 10)


# --- Johto: US ---------------------------------------------------------------------------


def zephyr(f: Facts) -> bool:
    return _traded(f, "us")


def hive(f: Facts) -> bool:
    return _protection_used(f, "us")


def plain(f: Facts) -> bool:
    return any(
        o.status == OrderStatus.FILLED
        and o.side == "buy"
        and o.quantity != o.quantity.to_integral_value()
        and group_of_symbol(o.symbol) == "us"
        for o in f.orders
    )


def fog(f: Facts) -> bool:
    return _short_closed_by_you(f, "us", None, paid_financing=True)


def storm(f: Facts) -> bool:
    return _distinct_symbols(f, "us", 5)


def mineral(f: Facts) -> bool:
    return _protected_streak(f, "us", 10)


def glacier(f: Facts) -> bool:
    return _sim_day(f, "us")


def rising(f: Facts) -> bool:
    return _capstone(f, "us", 10)


# --- Hoenn: crypto -----------------------------------------------------------------------


def stone(f: Facts) -> bool:
    return _traded(f, "crypto")


def knuckle(f: Facts) -> bool:
    return _protection_used(f, "crypto")


def dynamo(f: Facts) -> bool:
    shut = [markets.MARKETS[code] for code in _CRYPTO_CLOSED_MARKETS]
    return any(
        group_of_symbol(o.symbol) == "crypto"
        and all(hours.market_status(m, o.created_at).state == "closed" for m in shut)
        for o in f.orders
    )


def heat(f: Facts) -> bool:
    return _short_closed_by_you(f, "crypto", None, paid_financing=True)


def balance(f: Facts) -> bool:
    return _distinct_symbols(f, "crypto", 3)


def feather(f: Facts) -> bool:
    return _protected_streak(f, "crypto", 10)


def mind(f: Facts) -> bool:
    for bt in f.done_backtests:
        if not bt.symbols or any(group_of_symbol(s) != "crypto" for s in bt.symbols):
            continue
        results = bt.results or {}
        try:
            mine = Decimal(str(results["metrics"]["total_return_pct"]))
            hold = Decimal(str(results["buy_and_hold"]["total_return_pct"]))
        except KeyError, TypeError, ArithmeticError:
            continue
        if mine > hold:
            return True
    return False


def rain(f: Facts) -> bool:
    return _capstone(f, "crypto", 15)


# --- Sinnoh: global ----------------------------------------------------------------------


def coal(f: Facts) -> bool:
    return _traded(f, "global")


def forest(f: Facts) -> bool:
    return _protection_used(f, "global")


def cobble(f: Facts) -> bool:
    known = (
        markets.MARKETS[t.market_code]
        for t in f.by_group.get("global", [])
        if t.market_code in markets.MARKETS
    )
    countries = {m.country for m in known}
    return len(countries) >= 3


def fen(f: Facts) -> bool:
    return any(
        o.status == OrderStatus.FILLED and _pays_tax(o) and group_of_symbol(o.symbol) == "global"
        for o in f.orders
    )


def relic(f: Facts) -> bool:
    return _held(f, "global")


def mine(f: Facts) -> bool:
    return _protected_streak(f, "global", 10)


def icicle(f: Facts) -> bool:
    hk = markets.MARKETS["HKEX"]
    for o in f.orders:
        if o.status != OrderStatus.FILLED or o.filled_at is None or o.filled_at <= o.created_at:
            continue
        market = market_of_symbol(o.symbol)
        if market is None or market.code != "HKEX":
            continue
        if hours.market_status(hk, o.created_at).reason == "lunch break":
            return True
    return False


def beacon(f: Facts) -> bool:
    return _capstone(f, "global", 10)


# --- Elite Four: creators ----------------------------------------------------------------


def debut(f: Facts) -> bool:
    return any(f.done_windows.get(x.id) for x in f.listings)


def trusted(f: Facts) -> bool:
    return len(f.subscriptions) >= 10


def consistent(f: Facts) -> bool:
    for rows in f.done_windows.values():
        if len(rows) < 2:
            continue
        try:
            if all(Decimal(str(r.results["metrics"]["total_return_pct"])) > 0 for r in rows):
                return True
        except KeyError, TypeError, ArithmeticError:
            continue
    return False


def craftsman(f: Facts) -> bool:
    """A subscriber moved up to version 2+. An upgrade leaves no record of its own, but someone
    who subscribed before that version existed and now runs it must have upgraded."""
    for listing in f.listings:
        if listing.version < 2:
            continue
        # The first version after 1 (min over all that exist), when the newer code appeared.
        appeared = f.db.scalar(
            select(ListingVersion.created_at)
            .where(ListingVersion.listing_id == listing.id, ListingVersion.version >= 2)
            .order_by(ListingVersion.created_at)
            .limit(1)
        )
        if appeared is None:
            continue
        if any(
            s.listing_id == listing.id and s.listing_version >= 2 and s.created_at < appeared
            for s in f.subscriptions
        ):
            return True
    return False


CHECKS: dict[str, Callable[[Facts], bool]] = {
    name: fn for name, fn in globals().items() if name in BADGES and name != CHAMPION and callable(fn)
}


def champion(earned: set[str]) -> bool:
    """Every badge of any one region, and all four Elite Four."""
    if not all(b in earned for b in ELITE_FOUR):
        return False
    return any(
        all(b in earned for b in region_badges(region.id)) for region in REGIONS.values() if region.group
    )


def evaluate_user(db: Session, user_id: int, now: datetime) -> set[str]:
    """The ids of every badge the user has earned, from their data as it stands."""
    facts = Facts(db, user_id, now)
    earned = {badge_id for badge_id, check in CHECKS.items() if check(facts)}
    if champion(earned):
        earned.add(CHAMPION)
    return earned
