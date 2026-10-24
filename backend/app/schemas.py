from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal

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


class SimSessionIn(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10)
    interval: str = "1m"
    start_date: date
    end_date: date
    speed: int = Field(default=60, ge=1, le=200, description="Bars per second while running")

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


class SimSessionStateOut(SimSessionOut):
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


# --- backtests ----------------------------------------------------------------------------


class BacktestBrokersIn(BaseModel):
    """Broker per segment; a segment left out uses the live account's choice."""

    india: str | None = None
    international: str | None = None
    crypto: str | None = None


class BacktestIn(BaseModel):
    strategy: str = Field(description="Key of a predefined algorithm, from /api/algos/library")
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
