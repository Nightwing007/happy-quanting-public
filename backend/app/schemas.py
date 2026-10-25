from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    computed_field,
    field_validator,
)

from app.market_data.base import TRADABLE_TYPES, Instrument, Quote
from app.trading import hours
from app.trading.errors import UnsupportedMarket
from app.trading.markets import MARKETS, ShortRule, market_for

_PERCENT_STEP = Decimal("0.01")

# f"{v:f}" rather than str(): str(Decimal("0.00000001")) is "1E-8", which the frontend can't read.
Money = Annotated[Decimal, PlainSerializer(lambda v: f"{v:f}", return_type=str, when_used="json")]


class InstrumentOut(BaseModel):
    symbol: str
    name: str
    exchange: str
    type: str
    currency: str
    tradable: bool

    @classmethod
    def from_instrument(cls, inst: Instrument) -> InstrumentOut:
        return cls(
            symbol=inst.symbol,
            name=inst.name,
            exchange=inst.exchange,
            type=inst.type,
            currency=inst.currency,
            tradable=inst.type in TRADABLE_TYPES,
        )


class ShortRuleOut(BaseModel):
    """How shorting works on a market, for the ticket to explain it. Absent where it isn't offered."""

    style: Literal["intraday", "overnight", "margin"]
    margin_percent: Money
    borrow_percent_year: Money
    square_off_minutes_before_close: int | None
    min_shortable_step: Money

    @classmethod
    def from_rule(cls, rule: ShortRule) -> ShortRuleOut:
        return cls(
            style=rule.style,  # type: ignore[arg-type]
            margin_percent=rule.margin_percent,
            borrow_percent_year=rule.borrow_percent_year,
            square_off_minutes_before_close=rule.square_off_minutes_before_close,
            min_shortable_step=rule.min_shortable_step,
        )


class MarketStatusOut(BaseModel):
    code: str
    name: str
    state: Literal["open", "closed", "unknown"]
    is_open: bool
    next_open: datetime | None
    next_close: datetime | None
    timezone: str  # IANA name; label and times are in this zone
    reason: str  # why it is closed: "weekend", "holiday", "lunch break"...; empty otherwise
    label: str  # "Market open · closes 15:30 IST"
    quantity_step: Money  # smallest tradable increment, e.g. 0.0001
    short_selling: ShortRuleOut | None  # None: shorting isn't offered on this market
    lot_exits: Literal["specific", "fifo"]  # can an exit name its lot, or does it take the oldest


def _market_out(quote: Quote) -> MarketStatusOut | None:
    # Indexes and currencies have no market to trade on; neither do exchanges we don't model.
    if quote.type not in TRADABLE_TYPES:
        return None
    try:
        market = market_for(quote.symbol, quote.type)
    except UnsupportedMarket:
        return None
    status = hours.market_status(market)
    return MarketStatusOut(
        code=market.code,
        name=market.name,
        state=status.state,
        is_open=status.is_open,
        next_open=status.next_open,
        next_close=status.next_close,
        timezone=status.timezone,
        reason=status.reason,
        label=hours.status_label(market, status),
        quantity_step=market.quantity_step,
        short_selling=ShortRuleOut.from_rule(market.short_rule) if market.short_rule else None,
        lot_exits=market.lot_exits,  # type: ignore[arg-type]
    )


class QuoteOut(BaseModel):
    symbol: str
    name: str
    exchange: str
    type: str
    currency: str
    tradable: bool
    price: Money
    previous_close: Money | None
    change: Money | None
    change_percent: Money | None
    as_of: int
    market: MarketStatusOut | None

    @classmethod
    def from_quote(cls, quote: Quote) -> QuoteOut:
        change = change_percent = None
        if quote.previous_close:  # None or zero: no meaningful day change
            change = quote.price - quote.previous_close
            change_percent = (change / quote.previous_close * 100).quantize(
                _PERCENT_STEP, rounding=ROUND_HALF_UP
            )
        return cls(
            symbol=quote.symbol,
            name=quote.name,
            exchange=quote.exchange,
            type=quote.type,
            currency=quote.currency,
            tradable=quote.type in TRADABLE_TYPES,
            price=quote.price,
            previous_close=quote.previous_close,
            change=change,
            change_percent=change_percent,
            as_of=quote.as_of,
            market=_market_out(quote),
        )


class BarOut(BaseModel):
    time: str | int
    open: Money
    high: Money
    low: Money
    close: Money
    volume: int


class IndicatorPoint(BaseModel):
    time: str | int
    value: float  # chart value, not money


class IndicatorSeriesOut(BaseModel):
    name: str
    period: int
    pane: Literal["price", "own"]
    label: str
    points: list[IndicatorPoint]


class BarsOut(BaseModel):
    symbol: str
    interval: str
    range: str
    currency: str
    bars: list[BarOut]
    indicators: list[IndicatorSeriesOut]


class HistoryLimitOut(BaseModel):
    interval: str
    earliest: date | None  # first day Yahoo serves for this interval; None means no limit


class HistoryLimitsOut(BaseModel):
    today: date
    limits: list[HistoryLimitOut]


class AccountOut(BaseModel):
    currency: str
    cash: Money
    starting_cash: Money
    realized_pnl: Money
    margin_used: Money
    created_at: datetime


class ChargeOut(BaseModel):
    """One line of a trade's costs. Also the shape stored on the order, so what is saved is
    exactly what is served."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    category: str
    description: str
    amount: Money  # account currency
    native_amount: Money
    native_currency: str


class ChargesPaidOut(BaseModel):
    total: Money
    by_category: dict[str, Money]


class HoldingOut(BaseModel):
    """Open trades of one symbol and direction, pooled. Computed, never stored."""

    symbol: str
    name: str
    currency: str
    direction: Literal["long", "short"]
    quantity: Money
    avg_price: Money  # average entry price, instrument currency
    cost_basis: Money  # entry value + entry charges still on the open trades
    margin_blocked: Money
    last_price: Money | None
    fx_rate: Money | None
    # A long's market value; for a short, what buying the shares back would cost right now.
    market_value: Money
    unrealized_pnl: Money
    unrealized_pct: Money | None
    price_unavailable: bool
    # The price (instrument currency) where closing now returns everything put in, exit charges
    # included: an exit at or above it for a long, a cover at or below it for a short.
    break_even_price: Money | None
    trade_count: int


class ProtectionOutcomeOut(BaseModel):
    """What closing the trade's open part at `price` would leave you with, after every charge."""

    model_config = ConfigDict(from_attributes=True)

    price: Money  # instrument currency
    exit_value: Money  # account currency, before charges
    charges_total: Money
    realized_pnl: Money
    cash_change: Money


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    currency: str
    market_code: str
    direction: Literal["long", "short"]
    product: Literal["delivery", "intraday", "margin"]
    quantity: Money  # what the trade opened with
    open_quantity: Money
    entry_price: Money
    entry_fx_rate: Money
    entry_value: Money  # of the open part
    entry_charges: Money  # of the open part
    # Everything the entry paid, from the opening order's record. Unlike `entry_charges` it does
    # not fall as the trade is exited, so a closed trade still shows what it cost to get in.
    entry_charges_paid: Money
    cost_basis: Money
    margin_blocked: Money
    financing_paid: Money
    financing_accrued_until: datetime
    exit_value: Money
    exit_charges: Money
    realized_pnl: Money
    status: Literal["open", "closed"]
    closed_how: str | None
    opened_at: datetime
    closed_at: datetime | None
    opened_by_order_id: int | None
    lot_exits: Literal["specific", "fifo"]
    # Live figures, for open trades only.
    last_price: Money | None
    market_value: Money | None
    unrealized_pnl: Money | None
    unrealized_pct: Money | None
    price_unavailable: bool
    # Protection, instrument currency. The outcomes are what each price would leave you with.
    stop_price: Money | None
    target_price: Money | None
    protection_expires_at: datetime | None
    stop_outcome: ProtectionOutcomeOut | None
    target_outcome: ProtectionOutcomeOut | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timezone(self) -> str:
        """IANA zone of the exchange, so times can be shown on its clock."""
        return hours.timezone_of(MARKETS[self.market_code])


class PayoutOut(BaseModel):
    """One closed trade, start to finish. Every figure comes from the orders' immutable legs (and
    the trade's accumulated exit totals), never from the fields that shrink as a trade is exited."""

    trade_id: int
    symbol: str
    name: str
    currency: str  # the instrument's
    market_code: str
    direction: Literal["long", "short"]
    product: Literal["delivery", "intraday", "margin"]
    quantity: Money
    opened_at: datetime
    closed_at: datetime
    closed_how: Literal["exit", "sell", "cover", "square_off", "stop_loss", "target"]
    entry_price: Money  # instrument currency
    entry_value: Money  # what a long paid for the shares, what a short sold them for; before charges
    # What the exits left you with before any charge: a long's sale proceeds, a short's entry value
    # less what buying it back cost (can be negative).
    brought_in: Money
    exit_value: Money  # the sale proceeds, or what buying the short back cost; before charges
    entry_charge_lines: list[ChargeOut]
    entry_charges_total: Money
    exit_charge_lines: list[ChargeOut]  # lines with the same name across several exits are added
    exit_charges_total: Money
    financing_paid: Money  # borrow or funding on a short
    realized_pnl: Money  # the profit left over, after every charge and financing

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timezone(self) -> str:
        """IANA zone of the exchange, so times can be shown on its clock."""
        return hours.timezone_of(MARKETS[self.market_code])


class PayoutTotalsOut(BaseModel):
    trades_closed: int
    brought_in: Money
    charges: Money  # both ends of every closed trade
    financing: Money
    net_profit: Money


class PayoutsOut(BaseModel):
    currency: str  # of every figure except entry_price
    totals: PayoutTotalsOut  # over every closed trade, even when `limit` trims the list
    payouts: list[PayoutOut]  # newest close first


class PortfolioOut(BaseModel):
    currency: str
    cash: Money
    margin_used: Money
    available_cash: Money  # cash - margin_used; what a new order can spend
    starting_cash: Money
    invested: Money  # cost of the open longs
    market_value: Money  # value of the open longs
    short_value: Money  # shorts, marked to market: entry value less what covering costs now
    total_value: Money  # cash + market_value + short_value
    realized_pnl: Money
    unrealized_pnl: Money
    total_pnl: Money
    financing_paid: Money  # borrow and funding on shorts; already inside realized P&L
    charges_paid: ChargesPaidOut
    holdings: list[HoldingOut]
    trades: list[TradeOut]  # the open ones


class OrderLegOut(BaseModel):
    """What one leg of an order did. Also the shape stored on the order, so what is saved is
    exactly what is served."""

    kind: Literal["close_long", "open_short", "close_short", "open_long"]
    trade_id: int | None  # None only in a preview of a leg that opens a trade
    quantity: Money
    product: Literal["delivery", "intraday", "margin"]
    price: Money  # instrument currency
    value: Money  # account currency
    charges: list[ChargeOut]
    charges_total: Money
    # For a closing leg: the entry charges that were on the part it closed, released with it.
    entry_charges: Money
    cash_change: Money
    margin_change: Money  # + blocked, - released
    realized_pnl: Money | None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    currency: str
    side: str
    type: str
    quantity: Money
    limit_price: Money | None
    status: str
    fill_price: Money | None
    fx_rate: Money | None
    amount: Money | None
    realized_pnl: Money | None
    charges: list[ChargeOut]
    charges_total: Money
    trade_id: int | None
    origin: str
    cash_change: Money
    legs: list[OrderLegOut]
    note: str | None
    reject_reason: str | None
    created_at: datetime
    filled_at: datetime | None


class OrderIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    # Strings, not numbers: a JSON number is read as a float, so fractions (crypto) would
    # lose digits before the engine ever sees the value.
    quantity: str
    limit_price: str | None = None

    @field_validator("quantity", "limit_price", mode="before")
    @classmethod
    def _decimal_string(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return value
        label = "Quantity" if info.field_name == "quantity" else "Limit price"
        if not isinstance(value, str):
            raise ValueError(f'{label} must be sent as a string such as "0.5", not as a number.')
        try:
            Decimal(value.strip())
        except InvalidOperation:
            raise ValueError(f"{label} must be a number such as 10 or 0.5, but got '{value}'.") from None
        return value.strip()

    def quantity_decimal(self) -> Decimal:
        return Decimal(self.quantity)

    def limit_price_decimal(self) -> Decimal | None:
        return Decimal(self.limit_price) if self.limit_price is not None else None


class WatchlistItemOut(BaseModel):
    symbol: str
    name: str
    created_at: datetime
    # Live fields are null when the quote could not be fetched right now.
    price: Money | None = None
    change: Money | None = None
    change_percent: Money | None = None
    currency: str | None = None


class WatchlistIn(BaseModel):
    symbol: str


class BrokerRefOut(BaseModel):
    code: str
    name: str


class ExitIn(BaseModel):
    quantity: str | None = None  # default: the whole open part

    @field_validator("quantity", mode="before")
    @classmethod
    def _decimal_string(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError('Quantity must be sent as a string such as "0.5", not as a number.')
        try:
            Decimal(value.strip())
        except InvalidOperation:
            raise ValueError(f"Quantity must be a number such as 10 or 0.5, but got '{value}'.") from None
        return value.strip()

    def quantity_decimal(self) -> Decimal | None:
        return Decimal(self.quantity) if self.quantity is not None else None


class ProtectionIn(BaseModel):
    stop_price: str | None = None  # null clears it
    target_price: str | None = None

    @field_validator("stop_price", "target_price", mode="before")
    @classmethod
    def _decimal_string(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return value
        label = "Stop-loss" if info.field_name == "stop_price" else "Target"
        if not isinstance(value, str):
            raise ValueError(f'{label} must be sent as a string such as "1200.50", not as a number.')
        try:
            Decimal(value.strip())
        except InvalidOperation:
            raise ValueError(f"{label} must be a price such as 1200 or 1200.50, but got '{value}'.") from None
        return value.strip()

    def stop_decimal(self) -> Decimal | None:
        return Decimal(self.stop_price) if self.stop_price is not None else None

    def target_decimal(self) -> Decimal | None:
        return Decimal(self.target_price) if self.target_price is not None else None


class ProtectionPreviewOut(BaseModel):
    """Checks a stop-loss and target and shows what each would leave you with. Saves nothing."""

    current_price: Money
    currency: str
    stop_error: str | None
    target_error: str | None
    stop_outcome: ProtectionOutcomeOut | None
    target_outcome: ProtectionOutcomeOut | None


class OrderPreviewOut(BaseModel):
    """What an order would cost, from the same calculation that charges it."""

    symbol: str
    side: str
    quantity: Money
    price: Money  # the price the figures are worked out at
    value: Money  # instrument currency
    currency: str
    fx_rate: Money
    value_account: Money
    charges: list[ChargeOut]
    charges_total: Money
    cash_change: Money  # buy: -(value + charges); sell: +(value - charges); short: -charges
    margin_change: Money  # margin the order blocks (+) or releases (-)
    realized_pnl: Money | None  # what the closing legs would realize, None if nothing closes
    legs: list[OrderLegOut]  # one per trade touched, each with its own charges
    fifo: bool  # an exit took the oldest lots first, whichever trade it was started from
    note: str
    broker: BrokerRefOut
    market: BrokerRefOut


class SettingsOut(BaseModel):
    broker_india: str
    broker_international: str
    broker_crypto: str


class SettingsIn(BaseModel):
    broker_india: str | None = None
    broker_international: str | None = None
    broker_crypto: str | None = None


class MarketRefOut(BaseModel):
    code: str
    name: str
    currency: str


class BrokerOut(BaseModel):
    code: str
    name: str
    segment: str
    notes: str
    fx_markup_percent: Money
    markets: list[MarketRefOut]
    source: str
    checked: str


class SegmentBrokersOut(BaseModel):
    segment: str
    label: str
    brokers: list[BrokerOut]


class MetricRangeOut(BaseModel):
    """A sector's usual band for an equity metric; for a coin's 52-week position, the year's low and high."""

    low: Money
    high: Money
    label: str  # "Technology", or "All sectors" when the sector has no table of its own


class MetricOut(BaseModel):
    key: str
    label: str
    value: Money
    unit: Literal["x", "%", "currency", "units"]
    display_hint: Literal["multiple", "percent", "amount", "count", "position"]
    assessment: Literal["below usual", "typical", "above usual"] | None  # None: no sector range applies
    range: MetricRangeOut | None
    explanation: str
    better: Literal["lower", "higher", "depends"]
    meaning: str  # what the current assessment tends to indicate, in plain words
    # What being outside the usual range tends to indicate, each way. None where no range applies.
    if_below: str | None
    if_above: str | None


class OmittedMetricOut(BaseModel):
    """A metric left out on purpose, with why. Metrics that merely have no figure are not listed."""

    key: str
    label: str
    reason: str


class MetricsOut(BaseModel):
    symbol: str
    kind: Literal["equity", "crypto", "other"]
    sector: str | None
    currency: str
    metrics: list[MetricOut]
    omitted: list[OmittedMetricOut]
    note: str


# --- simulation ---------------------------------------------------------------------------


class SimStrategyIn(BaseModel):
    """What a sim runs. `library`: `key` (+ `params`); `mine`: `algo_id` of your saved algorithm;
    `source`: uploaded code (+ `params`); `listing`: a published marketplace listing, whose code and
    settings stay hidden from the tester."""

    kind: Literal["library", "mine", "source", "listing"]
    key: str | None = None
    algo_id: int | None = None
    source: str | None = None
    listing_id: int | None = None
    params: dict | None = None


class SimSessionIn(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10)
    interval: str | None = Field(
        default=None, description="Bar size; the strategy's own when there is one, else 1m"
    )
    start_date: date
    end_date: date
    speed: int = Field(default=60, ge=1, le=200, description="Bars per second while running")
    strategy: SimStrategyIn | None = None

    @field_validator("symbols")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return [s.strip().upper() for s in value if s.strip()]


class SimControlIn(BaseModel):
    action: Literal["start", "pause", "step", "reset"]
    steps: int | None = Field(default=None, ge=1, le=5000, description="Bars to play, for `step`")
    speed: int | None = Field(default=None, ge=1, le=200, description="New speed, bars per second")


class SimExchangeTimeOut(BaseModel):
    symbol: str
    timezone: str
    local_time: datetime  # the cursor in that exchange's own zone


class SimSessionOut(BaseModel):
    id: int
    account_id: int
    symbols: list[str]
    interval: str
    start_date: date
    end_date: date
    speed: int
    status: Literal["ready", "running", "paused", "finished"]
    cursor: datetime  # UTC
    exchange_times: list[SimExchangeTimeOut]
    progress_percent: float
    created_at: datetime


class SimLogOut(BaseModel):
    at: datetime
    text: str


class SimStrategyOut(BaseModel):
    """Who is trading in this sim. For a marketplace listing, `name` is the listing's and `creator`
    its creator's username; nothing else about it is shown."""

    kind: Literal["library", "mine", "source", "listing"]
    name: str
    interval: str
    creator: str | None = None


class SimSessionStateOut(SimSessionOut):
    strategy: SimStrategyOut | None = None
    # The strategy's last 100 log lines, only for code the requester may see (library, saved,
    # their own source); always empty for a listing.
    strategy_log: list[SimLogOut] = []
    # Only bars that had finished by the cursor, so the chart can never show the future. The
    # last `bars_limit` of each symbol, oldest first, stamped like a live chart (exchange-local).
    bars: dict[str, list[BarOut]]


class AlgoParamOut(BaseModel):
    """One setting of a predefined algorithm. Decimals are strings, like every money-like value."""

    name: str
    label: str
    kind: Literal["int", "decimal", "choice", "bool"]
    default: str | int | bool
    min: str | int | None
    max: str | int | None
    choices: list[str]
    help: str


class AlgoOut(BaseModel):
    key: str
    name: str
    description: str
    markets: list[str]
    interval: str
    warmup_bars: int
    parameters: list[AlgoParamOut]


class ValidateIn(BaseModel):
    source: str


class ProblemOut(BaseModel):
    line: int  # 1-based; 0 means the file as a whole
    col: int
    code: str
    message: str


class StrategyMetaOut(BaseModel):
    name: str
    description: str
    markets: list[str]
    interval: str
    parameters: list[AlgoParamOut]
    warmup_bars: int = 0


class RulesOut(BaseModel):
    markdown: str
    limits: dict[str, int]


class ValidationReportOut(BaseModel):
    ok: bool
    problems: list[ProblemOut]
    meta: StrategyMetaOut | None


# --- backtests ----------------------------------------------------------------------------


class BacktestBrokersIn(BaseModel):
    """Broker per segment; a segment left out uses the live account's choice."""

    india: str | None = None
    international: str | None = None
    crypto: str | None = None


class UserAlgoIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    strategy: str | None = Field(default=None, description="Key of the predefined algorithm this is built on")
    source: str | None = Field(
        default=None,
        description="Code written in the editor, checked against the code rules; instead of `strategy`",
    )
    graph: dict[str, Any] | None = Field(
        default=None,
        description="A block graph (see algos/blocks/compile.py), compiled to the saved `source`; instead of "
        "`strategy` or `source`",
    )
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("name", "description")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value:
            raise ValueError("Give the algorithm a name.")
        return value


class UserAlgoOut(BaseModel):
    id: int
    name: str
    description: str
    strategy: str
    strategy_name: str
    interval: str
    markets: list[str]
    params: dict[str, str | int | bool]
    source: str | None = None  # the owner's own code (these routes are owner-only)
    graph: dict[str, Any] | None = None  # the owner's block graph, same rule as `source`
    created_at: datetime


class BlockPortOut(BaseModel):
    name: str
    type: Literal["signal", "trigger"]
    multi: bool
    min: int


class BlockOut(BaseModel):
    """One block of the editor's palette."""

    type: str
    category: Literal["universe", "signal", "combine", "action", "risk", "custom"]
    label: str
    help: str
    params: list[AlgoParamOut]
    inputs: list[BlockPortOut]
    outputs: list[BlockPortOut]
    lookback: str  # bars of history needed, e.g. "$period + 1"
    custom_id: int | None = None
    custom_kind: Literal["group", "code"] | None = None


class BlockCatalogOut(BaseModel):
    blocks: list[BlockOut]


class CompileIn(BaseModel):
    graph: dict[str, Any]
    name: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=500)


class BlockProblemOut(BaseModel):
    """A graph problem names its block (`node_id`); a code problem has a `line` instead."""

    node_id: str | None = None
    line: int = 0
    col: int = 0
    code: str = ""
    message: str


class CompileOut(BaseModel):
    ok: bool
    problems: list[BlockProblemOut]
    source: str  # empty unless ok
    warmup_bars: int = 0


class CustomBlockIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["group", "code"]
    definition: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the block a name.")
        return value


class CustomBlockOut(BaseModel):
    id: int
    type: str  # "custom:<id>", what a graph node's `type` holds
    name: str
    kind: Literal["group", "code"]
    definition: dict[str, Any]
    created_at: datetime


class BacktestIn(BaseModel):
    strategy: str | None = Field(
        default=None, description="Key of a predefined algorithm, from /api/algos/library"
    )
    algo_id: int | None = Field(
        default=None,
        description="A saved algorithm from /api/algos/mine; `params` is laid over its saved settings",
    )
    source: str | None = Field(
        default=None,
        description="Uploaded strategy code to test before publishing; checked against the code rules. "
        "The result is visible only to the requester",
    )
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    symbols: list[str] = Field(min_length=1, max_length=10)
    interval: str
    start_date: date
    end_date: date
    starting_cash: Decimal | None = Field(default=None, gt=0, description="Default: STARTING_CASH")
    brokers: BacktestBrokersIn | None = None

    @field_validator("symbols")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return [s.strip().upper() for s in value if s.strip()]


class BacktestPointOut(BaseModel):
    """The account at the close of one bar (one day, for daily bars). All account currency."""

    at: datetime
    equity: Money  # cash + what the open positions are worth
    cash: Money
    positions: Money  # longs at market value, shorts at entry value less cost to cover
    buy_hold_equity: Money


class BacktestDrawdownOut(BaseModel):
    at: datetime
    strategy_pct: Money  # 0 at a new high, negative below it
    buy_hold_pct: Money


class BacktestTradeOut(BaseModel):
    id: int
    symbol: str
    name: str
    currency: str  # the instrument's; prices are in it, the rest in the account currency
    direction: Literal["long", "short"]
    product: str
    quantity: Money
    entry_at: datetime
    entry_price: Money
    exit_at: datetime | None
    exit_price: Money | None
    status: Literal["open", "closed"]
    closed_how: str | None
    entry_charges: Money
    exit_charges: Money
    charges_total: Money
    charges_by_category: dict[str, Money]
    financing: Money
    gross_pnl: Money | None  # before charges and financing; None while open
    realized_pnl: Money | None  # after every charge and financing; None while open
    unrealized_pnl: Money | None  # open trades, at the last price


class BacktestLogOut(BaseModel):
    at: datetime
    text: str


class BacktestMetricsOut(BaseModel):
    """Every figure is a string or null. Percentages are plain numbers ("12.34" is 12.34%)."""

    starting_cash: Money
    final_equity: Money
    total_return_pct: Money
    cagr_pct: Money | None
    cagr_note: str | None  # why CAGR is null
    max_drawdown_pct: Money  # positive: the deepest fall from a peak
    sharpe: Money | None
    sharpe_note: str | None  # why Sharpe is null
    trades_closed: int
    trades_open: int
    win_rate_pct: Money | None
    average_win: Money | None
    average_loss: Money | None  # negative
    profit_factor: Money | None
    total_charges: Money
    charges_by_category: dict[str, Money]
    gross_profit: Money | None  # sum of the winning closed trades before charges
    charges_pct_of_gross_profit: Money | None
    financing_paid: Money
    exposure_pct: Money  # share of bars with a position open
    # Capital in the market, as a share of equity at the closes: the average (flat counts as 0) and
    # the peak. None on runs saved before these existed (their results are stored as JSON).
    avg_exposure_pct: Money | None = None
    max_position_pct: Money | None = None


class BacktestPurchaseOut(BaseModel):
    symbol: str
    at: datetime
    quantity: Money
    price: Money
    charges: Money


class BacktestBuyHoldOut(BaseModel):
    """The same symbols bought at equal weight at the first fillable price, with real charges,
    and held to the end."""

    purchases: list[BacktestPurchaseOut]
    final_equity: Money
    total_return_pct: Money
    cagr_pct: Money | None
    max_drawdown_pct: Money
    total_charges: Money


class BacktestInstrumentOut(BaseModel):
    symbol: str
    name: str
    currency: str
    market: str


class BacktestResultsOut(BaseModel):
    strategy_key: str
    strategy_name: str
    params: dict[str, str | int | bool]
    account_currency: str
    interval: str
    instruments: list[BacktestInstrumentOut]
    bars: int  # bars (days, for daily) the run stepped through
    warmup_bars: int  # the strategy's own warmup, at the start of the range
    first_bar: datetime
    last_bar: datetime
    curve_stride: int  # 1: every bar is in the curves; n: every nth is (the metrics use all)
    equity_curve: list[BacktestPointOut]
    drawdown: list[BacktestDrawdownOut]
    trades: list[BacktestTradeOut]
    orders: list[OrderOut]
    logs: list[BacktestLogOut]
    errors: list[str]  # exceptions the strategy's own code raised
    notes: list[str]
    metrics: BacktestMetricsOut
    buy_and_hold: BacktestBuyHoldOut


class BacktestSummaryOut(BaseModel):
    id: int
    strategy_key: str
    params: dict
    symbols: list[str]
    interval: str
    start_date: date
    end_date: date
    starting_cash: Money
    account_currency: str
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    error: str | None
    created_at: datetime


class BacktestDetailOut(BacktestSummaryOut):
    results: BacktestResultsOut | None


class UserOut(BaseModel):
    """Who someone is. Never carries the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    avatar_url: str | None
    bio: str
    is_creator: bool


class SignupIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    bio: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = Field(default=None, max_length=500)


# --- marketplace ---------------------------------------------------------------------------
# Public listing models carry no code, settings, base algorithm or per-trade data, by design: a
# test walks their OpenAPI schemas for those names. `ListingOwnerOut` is the one that does, and
# only `/api/marketplace/mine` returns it.


class PerformanceMetricsOut(BaseModel):
    starting_cash: Money
    final_equity: Money
    total_return_pct: Money
    cagr_pct: Money | None
    cagr_note: str | None
    max_drawdown_pct: Money
    sharpe: Money | None
    sharpe_note: str | None
    win_rate_pct: Money | None
    profit_factor: Money | None
    trade_count: int  # closed trades; the trades themselves are never shown
    total_charges: Money
    exposure_pct: Money


class PerformancePointOut(BaseModel):
    at: datetime
    equity: Money
    buy_hold_equity: Money


class PerformanceDrawdownOut(BaseModel):
    at: datetime
    strategy_pct: Money
    buy_hold_pct: Money


class PerformanceBuyHoldOut(BaseModel):
    final_equity: Money
    total_return_pct: Money
    cagr_pct: Money | None
    max_drawdown_pct: Money
    total_charges: Money


class PerformanceResultsOut(BaseModel):
    """Totals and curves only. This is also what is stored for a listing."""

    account_currency: str
    metrics: PerformanceMetricsOut
    equity_curve: list[PerformancePointOut]
    drawdown: list[PerformanceDrawdownOut]
    buy_and_hold: PerformanceBuyHoldOut


class ListingPerformanceOut(BaseModel):
    window: Literal["3mo", "1y", "3y"]
    start: date
    end: date
    status: Literal["queued", "running", "done", "failed", "unavailable"]
    note: str | None
    computed_at: datetime | None
    results: PerformanceResultsOut | None


class ListingCreatorOut(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str | None
    badges: list[str] = []  # Elite Four and Champion only (badge ids)


class CreatorProfileOut(BaseModel):
    """A creator's public face. Built field by field: never the password hash or sessions."""

    username: str
    display_name: str
    avatar_url: str | None
    bio: str
    listing_count: int  # published listings


class ListingPublicOut(BaseModel):
    id: int
    name: str
    tagline: str
    description: str
    markets: list[str]
    interval: str
    fee_percent: Money
    version: int
    status: Literal["draft", "published", "retired"]
    creator: ListingCreatorOut
    headline: ListingPerformanceOut | None  # 1y when done, else the best window that is


class ListingVersionOut(BaseModel):
    """A version's number, date and notes. Never its code: that stays on the server."""

    version: int
    created_at: datetime
    changelog: str | None


class ListingDetailOut(ListingPublicOut):
    performance: list[ListingPerformanceOut]  # every window of the latest version
    versions: list[ListingVersionOut]


class ListingOwnerOut(ListingDetailOut):
    """Everything, including the code reference. Served only to the owner."""

    test_symbols: list[str]
    source: str | None
    strategy_key: str | None
    params: dict | None
    created_at: datetime
    updated_at: datetime


class ListingIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tagline: str = Field(default="", max_length=140)
    description: str = Field(default="", max_length=5000)
    markets: list[str] = Field(min_length=1)
    test_symbols: list[str] = Field(default_factory=list)
    interval: str | None = None  # the algorithm's own interval when left out
    fee_percent: Decimal
    source: str | None = None  # uploaded code, or...
    user_algo_id: int | None = None  # ...one of the owner's saved algorithms


class ListingUpdateIn(BaseModel):
    """Only the fields sent change. A new `source` or `params` makes a new version."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    tagline: str | None = Field(default=None, max_length=140)
    description: str | None = Field(default=None, max_length=5000)
    markets: list[str] | None = Field(default=None, min_length=1)
    test_symbols: list[str] | None = None
    interval: str | None = None
    fee_percent: Decimal | None = None
    source: str | None = None
    params: dict | None = None
    changelog: str | None = Field(default=None, max_length=500, description="Notes for the new version")


class SubscribeIn(BaseModel):
    symbols: list[str] = Field(min_length=1)
    capital: Decimal


class SubscriptionOut(BaseModel):
    """A subscriber's view of their own subscription: figures from the sub-account, never the
    algorithm's code or settings."""

    id: int
    listing_id: int
    listing_name: str
    listing_version: int  # the version this subscription runs
    latest_version: int  # the listing's newest
    upgrade_available: bool  # newer, published and the subscription is running: opt in with /upgrade
    symbols: list[str]
    status: Literal["active", "stopping", "stopped"]
    currency: str
    capital: Money
    equity: Money  # what the sub-account is worth now (once stopped: what came back)
    realized_pnl: Money
    unrealized_pnl: Money
    fee_percent: Money
    fees_paid: Money
    high_water_mark: Money
    created_at: datetime
    stopped_at: datetime | None


class DeploymentIn(BaseModel):
    """Give exactly one of `library_key` or `algo_id`. `params` are the settings to run with, over
    the library defaults or over the saved algorithm's own."""

    library_key: str | None = None
    algo_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(min_length=1)
    capital: Decimal
    name: str | None = Field(default=None, max_length=80)


class DeploymentOut(BaseModel):
    """The user's own algorithm running on a paper sub-account. Figures come from that account."""

    id: int
    name: str
    status: Literal["active", "paused", "stopping", "stopped"]
    strategy_kind: Literal["library", "mine"]
    strategy_key: str  # a library key; "" when the pinned code runs
    runs_code: bool  # the pinned snapshot is code (editor, block graph) rather than a library algorithm
    user_algo_id: int | None  # where it was copied from; None once that algorithm is deleted
    params: dict[str, Any]  # the settings pinned at deploy time
    symbols: list[str]
    currency: str
    capital: Money
    equity: Money  # what the sub-account is worth now (once stopped: what came back)
    realized_pnl: Money
    unrealized_pnl: Money
    created_at: datetime
    stopped_at: datetime | None


class DeploymentLogOut(BaseModel):
    at: datetime
    text: str


class DeploymentDetailOut(DeploymentOut):
    portfolio: PortfolioOut
    open_trades: list[TradeOut]
    orders: list[OrderOut]  # newest first
    log: list[DeploymentLogOut]  # the last 200 lines, oldest first; empty after a server restart
    total_charges: Money
    total_pnl: Money


class ListingEarningsOut(BaseModel):
    listing_id: int
    name: str
    subscribers: int  # a count; who they are is never shown
    active_subscribers: int
    fees_received: Money


class EarningsOut(BaseModel):
    currency: str
    total: Money
    listings: list[ListingEarningsOut]


# --- badges ---------------------------------------------------------------------------------


class BadgeOut(BaseModel):
    id: str
    name: str
    order: int
    hint: str  # the "Earned by" sentence
    kind: Literal["trader", "creator"]


class BadgeRegionOut(BaseModel):
    id: str
    name: str
    group: Literal["india", "us", "crypto", "global"] | None  # None: the Elite Four
    badges: list[BadgeOut]


class BadgeCatalogOut(BaseModel):
    regions: list[BadgeRegionOut]


class EarnedBadgeOut(BaseModel):
    id: str
    earned_at: datetime


class MyBadgesOut(BaseModel):
    earned: list[EarnedBadgeOut]
    new: list[str]  # earned and not yet shown as a toast
    backfill_summary: int | None  # badges awarded for past activity, until acknowledged


class BadgesSeenIn(BaseModel):
    ids: list[str]


class UserBadgesOut(BaseModel):
    username: str
    earned: list[EarnedBadgeOut]
