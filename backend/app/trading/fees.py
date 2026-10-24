"""Trading charges as data, and the one calculator that applies them.

Rates live in `markets.py` and `brokers.py` as `Fee` rows with their source and the date they
were checked. This module holds the shape of a fee and the arithmetic, nothing about any
particular market.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .money import money, trim8

if TYPE_CHECKING:
    from .brokers import Broker
    from .markets import Market

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

CATEGORIES = ("brokerage", "tax", "exchange", "regulatory", "depository", "gst", "fx")
_SIDES = ("buy", "sell", "both")


@dataclass(frozen=True)
class Fee:
    """One rule that can produce a charge. Percentages are in percent: 0.1 means 0.1%.

    The amount is `percent` of the trade value (or `maker_percent` for a resting limit order),
    plus `per_share` x quantity, plus `flat`; then `minimum` lifts it and `maximum` and
    `max_percent` (a cap as a percent of the trade value) cap it, caps last. That is how
    Interactive Brokers words its "min $1, max 1% of trade value".
    """

    name: str
    category: str
    description: str  # plain language, shown on hover
    percent: Decimal = ZERO
    maker_percent: Decimal | None = None
    per_share: Decimal = ZERO
    flat: Decimal = ZERO
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    max_percent: Decimal | None = None
    side: str = "both"
    only_types: frozenset[str] | None = None  # e.g. {"equity"}: UK stamp duty skips ETFs
    only_markets: frozenset[str] | None = None  # market codes; lets one broker price each market
    # Charged only when the trade value is above this, and then on the WHOLE value (or the whole
    # flat amount), not on the excess. That is how the UK PTM levy works: GBP 1.50 once a trade
    # is over GBP 10,000, not GBP 1.50 per GBP 10,000.
    above_value: Decimal | None = None
    round_up_to_whole: bool = False  # Hong Kong stamp duty rounds up to the next whole dollar
    # When set, the fee is `percent` of the sum of the already-computed charges in these
    # categories. This is how GST works: a tax on other charges, not on the trade.
    on_categories: frozenset[str] | None = None
    # Set when flat/per_share/minimum/maximum are in a fixed currency rather than the
    # instrument's. A fee in a different currency can only be a flat amount in the account
    # currency (there is only one exchange rate in play per trade).
    currency: str | None = None
    source: str = ""
    checked: str = ""  # YYYY-MM-DD

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown fee category {self.category!r} on {self.name!r}")
        if self.side not in _SIDES:
            raise ValueError(f"Unknown fee side {self.side!r} on {self.name!r}")


@dataclass(frozen=True)
class Charge:
    """A fee as actually levied on one trade."""

    name: str
    category: str
    description: str
    amount: Decimal  # account currency, 2 dp
    native_amount: Decimal  # the currency the charge was worked out in, 2 dp
    native_currency: str


def _applies(fee: Fee, market_code: str, side: str, instrument_type: str) -> bool:
    return (
        fee.side in ("both", side)
        and (fee.only_types is None or instrument_type in fee.only_types)
        and (fee.only_markets is None or market_code in fee.only_markets)
    )


def _fee_amount(fee: Fee, quantity: Decimal, value: Decimal, maker: bool) -> Decimal:
    """Unrounded amount of a non-`on_categories` fee, in the fee's own currency."""
    if fee.above_value is not None and value <= fee.above_value:
        return ZERO
    percent = fee.maker_percent if maker and fee.maker_percent is not None else fee.percent
    amount = value * percent / HUNDRED + quantity * fee.per_share + fee.flat
    if fee.minimum is not None:
        amount = max(amount, fee.minimum)
    if fee.maximum is not None:
        amount = min(amount, fee.maximum)
    if fee.max_percent is not None:
        amount = min(amount, value * fee.max_percent / HUNDRED)
    if fee.round_up_to_whole:
        amount = Decimal(math.ceil(amount))
    return amount


def calculate_charges(
    market: Market,
    broker: Broker,
    side: str,
    quantity: Decimal,
    price: Decimal,
    *,
    instrument_type: str,
    instrument_currency: str,
    account_currency: str,
    fx_rate: Decimal,
    maker: bool = False,
    product: str = "delivery",
) -> list[Charge]:
    """Every charge on one trade, in the order the lines should be shown.

    `product` picks the fee tables: an `intraday` trade uses the market's and the broker's
    intraday tables where they exist (different STT and stamp duty, no depository charge),
    every other product uses the ordinary ones.

    Order matters, and each step exists for a reason:
    1. Broker fees, then market fees, each worked out in the instrument's currency and rounded
       to 2 dp on its own, because a contract note rounds line by line.
    2. `on_categories` fees (GST) next, because they are a percentage of the already-rounded
       lines above; GST is charged on what the contract note shows, not on unrounded maths.
    3. Currency conversion last of all, so each line is first right in its own currency and is
       then converted and rounded again. Converting the trade value first would shift paise
       between lines. Charges that round to nothing are left out.
    The broker's FX markup (a cost of converting, not of trading) joins the conversion step.
    """
    value = quantity * price
    broker_fees, market_fees = broker.fees, market.fees
    if product == "intraday":
        if broker.intraday_fees is not None:
            broker_fees = broker.intraday_fees
        if market.intraday_fees is not None:
            market_fees = market.intraday_fees
    fees = [f for f in (*broker_fees, *market_fees) if _applies(f, market.code, side, instrument_type)]

    # (fee, native currency, native amount rounded to 2 dp)
    levied: list[tuple[Fee, str, Decimal]] = []
    for fee in (f for f in fees if f.on_categories is None):
        fee_ccy = fee.currency or instrument_currency
        if fee_ccy != instrument_currency:
            if fee_ccy != account_currency or fee.percent or fee.maker_percent:
                raise ValueError(
                    f"{fee.name}: a fee in {fee_ccy} can only be a flat amount in the account "
                    f"currency ({account_currency}), not a percentage"
                )
        native = money(_fee_amount(fee, quantity, value, maker))
        if native:
            levied.append((fee, fee_ccy, native))

    for fee in (f for f in fees if f.on_categories is not None):
        assert fee.on_categories is not None
        base = sum(
            (n for f, c, n in levied if f.category in fee.on_categories and c == instrument_currency),
            ZERO,
        )
        native = money(base * fee.percent / HUNDRED)
        if native:
            levied.append((fee, instrument_currency, native))

    def convert(native: Decimal, native_currency: str) -> Decimal:
        return native if native_currency == account_currency else money(native * fx_rate)

    charges = [
        Charge(f.name, f.category, f.description, convert(n, c), n, c) for f, c, n in levied
    ]  # fmt: skip

    if instrument_currency != account_currency and broker.fx_markup_percent > 0:
        markup = money(value * broker.fx_markup_percent / HUNDRED)
        if markup:
            charges.append(
                Charge(
                    "Currency conversion markup",
                    "fx",
                    f"{broker.name} converts {account_currency} to {instrument_currency} at a rate "
                    f"{broker.fx_markup_percent:f}% worse than the market rate.",
                    convert(markup, instrument_currency),
                    markup,
                    instrument_currency,
                )
            )
    return charges


def tick_for(instrument_type: str) -> Decimal:
    return Decimal("1E-8") if instrument_type == "crypto" else Decimal("0.01")


def break_even_price(
    market: Market,
    broker: Broker,
    *,
    quantity: Decimal,
    cost_basis: Decimal,
    instrument_type: str,
    instrument_currency: str,
    account_currency: str,
    fx_rate: Decimal,
    maker: bool = False,
    product: str = "delivery",
) -> Decimal:
    """The lowest price, on the instrument's tick, at which selling `quantity` returns at least
    `cost_basis` (everything paid to get in, entry charges included) after the exit charges.

    Exit charges depend on the exit price, so there is no closed form; this bisects on whole
    ticks. A fee that switches on above a value (the UK levy) can make net proceeds dip as the
    price rises, so across such a threshold the answer is a break-even, not the only one.
    """
    tick = tick_for(instrument_type)

    def net_at(ticks: int) -> Decimal:
        price = trim8(tick * ticks)
        proceeds = money(quantity * price * fx_rate)
        charges = calculate_charges(
            market,
            broker,
            "sell",
            quantity,
            price,
            instrument_type=instrument_type,
            instrument_currency=instrument_currency,
            account_currency=account_currency,
            fx_rate=fx_rate,
            maker=maker,
            product=product,
        )
        return proceeds - sum((c.amount for c in charges), ZERO)

    if cost_basis <= 0:
        return ZERO
    # Start at the no-fee price and double until the exit pays, then bisect between the last
    # failing and the first passing tick.
    high = max(math.ceil(cost_basis / (quantity * fx_rate) / tick), 1)
    low = 0
    for _ in range(80):
        if net_at(high) >= cost_basis:
            break
        low, high = high, high * 2
    else:
        raise ValueError("Charges are so large that no exit price recovers the cost")
    while high - low > 1:
        mid = (low + high) // 2
        if net_at(mid) >= cost_basis:
            high = mid
        else:
            low = mid
    return trim8(tick * high)


def break_even_cover_price(
    market: Market,
    broker: Broker,
    *,
    quantity: Decimal,
    entry_value: Decimal,
    entry_charges: Decimal,
    instrument_type: str,
    instrument_currency: str,
    account_currency: str,
    fx_rate: Decimal,
    maker: bool = False,
    product: str = "margin",
) -> Decimal:
    """The highest price, on the instrument's tick, at which buying `quantity` back still
    returns what the short took in, after paying the entry charges still on it and the cover's
    own charges. Above it the short is losing money.

    The mirror of `break_even_price`: the cover's cost rises with the price, so net proceeds
    fall as the price rises and this bisects for the last tick where they still cover the entry
    charges. Raises ValueError when even a free cover could not recover the charges.
    """
    tick = tick_for(instrument_type)

    def net_at(ticks: int) -> Decimal:
        price = trim8(tick * ticks)
        cost = money(quantity * price * fx_rate)
        charges = calculate_charges(
            market,
            broker,
            "buy",
            quantity,
            price,
            instrument_type=instrument_type,
            instrument_currency=instrument_currency,
            account_currency=account_currency,
            fx_rate=fx_rate,
            maker=maker,
            product=product,
        )
        return entry_value - cost - sum((c.amount for c in charges), ZERO)

    low = 0
    if net_at(low) < entry_charges:
        raise ValueError("The charges are so large that no cover price recovers them")
    # Past entry_value / (quantity x fx) the cover costs more than the short took in.
    high = math.ceil(entry_value / (quantity * fx_rate) / tick) + 1
    while high - low > 1:
        mid = (low + high) // 2
        if net_at(mid) >= entry_charges:
            low = mid
        else:
            high = mid
    return trim8(tick * low)
