// Autocomplete hints for the strategy API. Mirrors, by hand, `StrategyContext` and `Indicators` in
// backend/app/algos/api.py (names, arguments, one-line docs): change both together.

export type Hint = {
  name: string;
  kind: "method" | "property";
  /** Shown beside the name, e.g. "(symbol, quantity=None, percent_of_cash=None)". */
  signature: string;
  /** Text inserted (a Monaco snippet); defaults to the name. */
  snippet?: string;
  doc: string;
};

/** Members of `ctx`, the object every hook receives. */
export const CTX_MEMBERS: Hint[] = [
  {
    name: "buy",
    kind: "method",
    signature: "(symbol, quantity=None, percent_of_cash=None)",
    snippet: "buy(${1:symbol}, percent_of_cash=${2:10})",
    doc: "Buy shares, or as many as percent_of_cash of available cash buys. Fills at the next bar.",
  },
  {
    name: "sell",
    kind: "method",
    signature: "(symbol, quantity=None, percent_of_cash=None)",
    snippet: "sell(${1:symbol})",
    doc: "Sell part of what you hold long (all of it with no amount). Never opens a short.",
  },
  {
    name: "short",
    kind: "method",
    signature: "(symbol, quantity=None, percent_of_cash=None)",
    snippet: "short(${1:symbol}, percent_of_cash=${2:10})",
    doc: "Sell shares you don't hold; only where the market offers shorting.",
  },
  {
    name: "exit",
    kind: "method",
    signature: "(trade_id)",
    snippet: "exit(${1:trade.id})",
    doc: "Close all of one open trade at the market.",
  },
  {
    name: "set_protection",
    kind: "method",
    signature: "(trade_id, stop=None, target=None)",
    snippet: "set_protection(${1:trade.id}, stop=${2:None}, target=${3:None})",
    doc: "Set a trade's stop-loss and target now; both None clears them.",
  },
  {
    name: "bars",
    kind: "method",
    signature: "(symbol, n)",
    snippet: "bars(${1:symbol}, ${2:20})",
    doc: "The last n finished bars, oldest first (open, high, low, close, volume).",
  },
  {
    name: "close_series",
    kind: "method",
    signature: "(symbol, n)",
    snippet: "close_series(${1:symbol}, ${2:20})",
    doc: "Closing prices of the last n bars as floats, for the indicators.",
  },
  {
    name: "price",
    kind: "method",
    signature: "(symbol)",
    snippet: "price(${1:symbol})",
    doc: "The latest price: the close of the last finished bar.",
  },
  {
    name: "position",
    kind: "method",
    signature: "(symbol)",
    snippet: "position(${1:symbol})",
    doc: "Net holding in a symbol: quantity (negative = short) and avg_price.",
  },
  {
    name: "open_trades",
    kind: "method",
    signature: "(symbol=None)",
    snippet: "open_trades(${1:symbol})",
    doc: "Your open trades, for one symbol or all of them.",
  },
  { name: "cash", kind: "property", signature: "", doc: "Cash in the account." },
  {
    name: "available_cash",
    kind: "property",
    signature: "",
    doc: "Cash less the margin blocked by shorts: what a new order can use.",
  },
  { name: "params", kind: "property", signature: "", doc: "This run's settings, as a dict keyed by PARAMETERS name." },
  { name: "symbols", kind: "property", signature: "", doc: "The symbols this run trades, as a tuple." },
  { name: "now", kind: "property", signature: "", doc: "The run's clock: the moment the latest bar closed." },
  {
    name: "log",
    kind: "method",
    signature: "(message)",
    snippet: "log(${1:message})",
    doc: "Write a line to the strategy log (shown with backtest and sim results).",
  },
  { name: "indicators", kind: "property", signature: "", doc: "sma, ema, rsi, atr, bollinger, highest, lowest on lists of floats." },
];

/** Functions of `ctx.indicators`. Each returns a list as long as its input, with nan until a window fills. */
export const INDICATOR_FUNCTIONS: Hint[] = [
  {
    name: "sma",
    kind: "method",
    signature: "(values, period)",
    snippet: "sma(${1:closes}, ${2:20})",
    doc: "Simple moving average.",
  },
  {
    name: "ema",
    kind: "method",
    signature: "(values, period)",
    snippet: "ema(${1:closes}, ${2:20})",
    doc: "Exponential moving average.",
  },
  {
    name: "rsi",
    kind: "method",
    signature: "(values, period=14)",
    snippet: "rsi(${1:closes}, ${2:14})",
    doc: "Relative strength index, 0 to 100.",
  },
  {
    name: "atr",
    kind: "method",
    signature: "(highs, lows, closes, period=14)",
    snippet: "atr(${1:highs}, ${2:lows}, ${3:closes}, ${4:14})",
    doc: "Average true range: how far price typically moves in a bar.",
  },
  {
    name: "bollinger",
    kind: "method",
    signature: "(values, period=20, k=2.0)",
    snippet: "bollinger(${1:closes}, ${2:20}, ${3:2.0})",
    doc: "Returns (middle, upper, lower) bands, k deviations either side of the average.",
  },
  {
    name: "highest",
    kind: "method",
    signature: "(values, period)",
    snippet: "highest(${1:highs}, ${2:20})",
    doc: "Highest value over the last period bars.",
  },
  {
    name: "lowest",
    kind: "method",
    signature: "(values, period)",
    snippet: "lowest(${1:lows}, ${2:20})",
    doc: "Lowest value over the last period bars.",
  },
];
