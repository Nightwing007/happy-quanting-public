// The one place trading and finance terms are defined. Add terms here and show them with
// <Term id="..."> (components/term.tsx); never write a definition inline in a component.
// `good` only where a genuine rule of thumb exists. Levels (SMA, ATR...) say they aren't scores.
// `{period}` in `short` is filled from <Term params={{ period: 20 }}>, and reads "N" otherwise.

export type GlossaryEntry = {
  /** Display name, with the long form when the label is an abbreviation. */
  term: string;
  /** One plain sentence: what it is. */
  short: string;
  /** How to read it: what high, low or crossing values tend to mean. */
  read: string;
  /** A rule of thumb for a good value, only where a real one exists. */
  good?: string;
};

export const GLOSSARY = {
  // Chart
  candle: {
    term: "Candle",
    short: "One bar on the chart that shows how the price moved over a single period (a day, an hour...).",
    read: "The thick body runs from the open to the close, green if the price closed higher and red if lower. The thin wicks reach the period's highest and lowest prices.",
  },
  ohlc: {
    term: "OHLC — Open, High, Low, Close",
    short: "The four prices that describe one candle: where it started, its highest, its lowest and where it ended.",
    read: "Close is the price most indicators use. A big gap between high and low means the price swung a lot in that period.",
  },
  volume: {
    term: "Volume",
    short: "How many shares or units traded in the period.",
    read: "Volume isn't a score, it's a count. Tall bars tend to mean busy trading, and a price move on high volume is often read as more convincing than one on low volume.",
  },
  sma: {
    term: "SMA — Simple moving average",
    short: "The average closing price of the last {period} bars.",
    read: "SMA isn't a score — it's the average price of the last N bars. Price above a rising SMA suggests an uptrend; a short SMA crossing above a long one is a classic buy signal.",
  },
  ema: {
    term: "EMA — Exponential moving average",
    short: "Like an SMA over the last {period} bars, but recent prices count for more.",
    read: "EMA isn't a score either, it's a price level. It reacts faster than an SMA, so it turns sooner but also gives more false signals. Price above a rising EMA is often read as an uptrend.",
  },
  rsi: {
    term: "RSI — Relative strength index",
    short: "A 0 to 100 gauge of how strongly the price has risen or fallen over the last {period} bars.",
    read: "High values mean recent gains dominated, low values mean recent losses did. It describes momentum and is not a prediction.",
    good: "A rule of thumb: above 70 is often called overbought and below 30 oversold.",
  },
  bollinger: {
    term: "Bollinger bands",
    short: "A channel drawn around a moving average, usually two standard deviations above and below it.",
    read: "Bands are price levels, not scores. Narrow bands tend to mean a quiet market and wide bands a volatile one. Price touching the outer band is often read as stretched, not as a signal on its own.",
  },
  atr: {
    term: "ATR — Average true range",
    short: "The average distance the price travels in one bar over the last {period} bars, gaps included.",
    read: "ATR is a level in price units, not a score. A higher ATR means bigger typical swings, so people often set stops a multiple of ATR away.",
  },
  donchian: {
    term: "Donchian channel",
    short: "The highest high and lowest low of the last {period} bars, drawn as two lines.",
    read: "These are price levels, not scores. Price closing above the upper line (a new N-bar high) is a classic breakout buy signal, and below the lower line a breakdown.",
  },
  timeframe: {
    term: "Timeframe and interval",
    short: "How far back the chart looks (range) and how much time each candle covers (interval).",
    read: "Short timeframes with small intervals show day-to-day noise. Long ones with daily or weekly candles show the bigger trend.",
  },
  crossover: {
    term: "Crossover",
    short: "When one line moves from below another to above it, or the other way round.",
    read: "A fast average crossing above a slow one is often read as a buy signal, and crossing below as a sell signal. Crossovers lag the price and give false signals in choppy markets.",
  },
  overbought: {
    term: "Overbought",
    short: "A label for when an indicator says the price has risen unusually fast.",
    read: "It tends to be read as a hint that a pause or pullback is more likely, but strong trends can stay overbought for a long time.",
    good: "With RSI, a rule of thumb is a reading above 70.",
  },
  oversold: {
    term: "Oversold",
    short: "A label for when an indicator says the price has fallen unusually fast.",
    read: "It tends to be read as a hint that a bounce is more likely, but a falling price can stay oversold for a long time.",
    good: "With RSI, a rule of thumb is a reading below 30.",
  },

  // Orders and trading
  market_order: {
    term: "Market order",
    short: "An order to buy or sell right away at the best price available.",
    read: "You get the fill quickly but not a chosen price, so the price you pay can differ slightly from the one you saw.",
  },
  limit_order: {
    term: "Limit order",
    short: "An order to buy at your price or lower, or sell at your price or higher.",
    read: "You control the price but the order may never fill if the market doesn't reach it. It waits until it does or you cancel it.",
  },
  amo: {
    term: "AMO — After-market order (waiting order)",
    short: "An order placed while the market is closed, which waits and is sent when the market opens.",
    read: "It fills at the next open's price, which can differ from the last close you see now.",
  },
  delivery: {
    term: "Delivery",
    short: "Buying shares and keeping them in your account, with no deadline to sell.",
    read: "You pay the full price up front and own the shares until you sell. Delivery carries different charges from intraday.",
  },
  intraday: {
    term: "Intraday",
    short: "Buying and selling the same shares within one trading day.",
    read: "Positions still open near the close are squared off (closed) automatically. Intraday usually has lower brokerage and needs less margin.",
  },
  short: {
    term: "Short",
    short: "Selling first and buying back later, hoping to buy back cheaper.",
    read: "You gain if the price falls and lose if it rises. Losses on a short have no upper limit, which is why margin is required.",
  },
  cover: {
    term: "Cover",
    short: "Buying back a short position to close it.",
    read: "Covering below your selling price is a profit and above it is a loss.",
  },
  square_off: {
    term: "Square-off",
    short: "Closing a position by doing the opposite trade, so nothing remains open.",
    read: "Intraday positions are squared off automatically before the market closes if you haven't done it yourself.",
  },
  margin: {
    term: "Margin",
    short: "The part of your cash set aside as a deposit to hold a leveraged or short position.",
    read: "Margin isn't a cost, it's locked cash that comes back when the position closes. More margin used means less cash free for new trades.",
  },
  available_cash: {
    term: "Available cash",
    short: "Cash you can spend on new orders right now.",
    read: "It is your cash minus margin locked in open positions and cash reserved for waiting orders.",
  },
  long: {
    term: "Long",
    short: "Owning a position that gains when the price rises.",
    read: "You buy first and sell later. The most you can lose is what you paid.",
  },
  fifo_exit: {
    term: "FIFO exit",
    short: "First in, first out: the oldest shares you bought are sold first.",
    read: "It is the simple default when you sell a quantity without picking a specific purchase.",
  },
  lot_exit: {
    term: "Specific-lot exit",
    short: "Choosing exactly which purchase (lot) to sell.",
    read: "Different lots have different buy prices, so the choice changes your profit or loss on this sale.",
  },
  stop_loss: {
    term: "Stop-loss",
    short: "A price at which a trade is closed automatically at the market price, to limit a loss.",
    read: "It protects against large losses but can trigger on a brief dip, and the fill can be worse than the stop price in a fast market.",
  },
  target: {
    term: "Target",
    short: "A price at which a trade is closed automatically at the market price, to take a profit.",
    read: "It locks in a gain without watching the screen, but it also ends the trade if the price would have kept rising.",
  },
  gtt: {
    term: "GTT / one-cancels-other",
    short: "A stop and a target set together on one trade: when either triggers, the other is cancelled.",
    read: "It lets you define the worst and best outcome you accept before the price gets there.",
  },
  break_even: {
    term: "Break-even",
    short: "The price you need to sell at to get back everything you paid, charges included.",
    read: "It sits slightly above your average entry for a long position because charges have to be covered first.",
  },
  avg_entry: {
    term: "Avg entry",
    short: "The average price you paid per share across your open buys.",
    read: "Price above your average entry means the position shows an unrealized gain, and below it an unrealized loss, before charges.",
  },
  realized_pnl: {
    term: "Realized P&L",
    short: "Profit or loss from trades you have already closed, after charges.",
    read: "It is locked in and doesn't change with the market any more.",
  },
  unrealized_pnl: {
    term: "Unrealized P&L",
    short: "Profit or loss on positions still open, at today's price.",
    read: "It moves with the price and only becomes real when you close the position.",
  },

  // Charges
  brokerage: {
    term: "Brokerage",
    short: "The fee the broker charges for executing a trade.",
    read: "It is usually a small flat amount or a small percentage, and is charged on both the buy and the sell.",
  },
  stt: {
    term: "STT — Securities transaction tax",
    short: "An Indian government tax charged on the value of share trades on exchanges.",
    read: "Depending on the trade type it applies on the sell side only or on both sides. It is part of your cost to trade.",
  },
  stamp_duty: {
    term: "Stamp duty",
    short: "An Indian state-levied tax charged on the buy side of a trade.",
    read: "It is a small percentage of the traded value and you pay it only when buying.",
  },
  exchange_charge: {
    term: "Exchange transaction charge",
    short: "A small fee the stock exchange charges on the value traded.",
    read: "It is a tiny percentage of each trade and is charged on both buys and sells.",
  },
  sebi_fee: {
    term: "SEBI fee",
    short: "A tiny turnover fee that goes to SEBI, India's market regulator.",
    read: "It is a very small amount per crore traded, so it rarely matters for small trades.",
  },
  gst: {
    term: "GST — Goods and services tax",
    short: "A tax on the brokerage and exchange fees, not on the shares themselves.",
    read: "It is charged on top of those fees, so lower brokerage means lower GST.",
  },
  dp_charge: {
    term: "DP charge — Depository participant charge",
    short: "A flat fee when shares are sold out of your demat account.",
    read: "It is charged once per sell of a delivery holding, however many shares you sell.",
  },
  fx_markup: {
    term: "FX markup",
    short: "An extra margin added to the exchange rate when money is converted between currencies.",
    read: "It is a hidden cost: the rate you get is a bit worse than the market rate.",
  },
  borrow_fee: {
    term: "Borrow fee",
    short: "Interest paid for borrowing shares to hold a short position.",
    read: "It grows with the time the short stays open, so a long-held short costs more.",
  },
  funding_fee: {
    term: "Funding fee",
    short: "A periodic payment between traders holding crypto leveraged positions.",
    read: "Depending on the market it is paid or received. It builds up for as long as the position stays open.",
  },

  // Backtest and results
  backtest: {
    term: "Backtest",
    short: "Running a strategy on past prices to see how it would have done.",
    read: "A good backtest doesn't promise future results. Markets change, and a strategy tuned to the past can fail afterwards.",
  },
  total_return: {
    term: "Total return",
    short: "How much the account grew or shrank over the whole test, as a percentage.",
    read: "It ignores how bumpy the ride was and how long it took, so read it together with max drawdown and the buy-and-hold result.",
    good: "A rule of thumb: compare it with buy-and-hold over the same period, since beating that is the bar.",
  },
  cagr: {
    term: "CAGR — Compound annual growth rate",
    short: "The steady yearly growth rate that would give the same total return.",
    read: "It lets you compare tests of different lengths on a per-year basis.",
  },
  max_drawdown: {
    term: "Max drawdown",
    short: "The biggest drop from a peak to a later low in the account value.",
    read: "It shows the worst losing stretch you would have sat through.",
    good: "Smaller is better. Compare it with buy-and-hold: a strategy that earns similar returns with a smaller drawdown is easier to live with.",
  },
  sharpe: {
    term: "Sharpe ratio",
    short: "Return earned per unit of ups and downs (volatility).",
    read: "Higher means the gains were steadier for the risk taken. It is noisy on short tests.",
    good: "A rule of thumb: above 1 is decent and above 2 is strong; below 0.5 is weak.",
  },
  win_rate: {
    term: "Win rate",
    short: "The share of closed trades that made a profit.",
    read: "A high win rate isn't enough on its own: many small wins can be wiped out by a few large losses.",
  },
  profit_factor: {
    term: "Profit factor",
    short: "Total profit from winning trades divided by total loss from losing ones.",
    read: "Above 1 means winners outweighed losers, below 1 means the reverse.",
    good: "A rule of thumb: above 1.5 is often called good. Very high values on few trades are usually luck.",
  },
  exposure: {
    term: "Exposure",
    short: "The share of the test period during which the strategy held a position.",
    read: "Low exposure means the strategy was mostly in cash, so it had less chance to gain or lose.",
  },
  buy_and_hold: {
    term: "Buy-and-hold",
    short: "The result of buying at the start and doing nothing until the end.",
    read: "It is the benchmark: a strategy that can't beat it after charges adds complexity without adding value.",
  },
  warmup_bars: {
    term: "Warmup bars",
    short: "Earlier bars loaded before the test starts, only so indicators have enough history.",
    read: "No trades happen during warmup. A 200-bar SMA needs about 200 bars before its first value.",
  },
  next_bar_fill: {
    term: "Next-bar fill",
    short: "An order decided on one bar is filled at the next bar's open.",
    read: "It matches real life, where you can't trade at a price you've only just seen close.",
  },
  look_ahead: {
    term: "Look-ahead",
    short: "Accidentally using information from the future when making a decision.",
    read: "It makes backtests look far better than reality. The engine prevents it by only showing completed bars.",
  },

  // Company metrics
  pe: {
    term: "P/E — Price to earnings",
    short: "The share price divided by the company's yearly profit per share.",
    read: "A higher P/E means investors pay more for each rupee or dollar of profit, which often reflects expected growth.",
    good: "A rule of thumb: compare it with companies in the same sector, not across sectors.",
  },
  pb: {
    term: "P/B — Price to book",
    short: "The share price divided by the company's net assets per share.",
    read: "Below 1 means the market values the company at less than its accounting assets. Asset-light businesses naturally have a high P/B.",
    good: "A rule of thumb: compare it with the sector's range.",
  },
  roe: {
    term: "ROE — Return on equity",
    short: "Yearly profit as a percentage of the money shareholders have put in.",
    read: "Higher means the company turns shareholders' money into profit more effectively, but heavy debt can inflate it.",
    good: "A rule of thumb: a steady ROE of around 15% or more is often seen as healthy.",
  },
  debt_to_equity: {
    term: "Debt-to-equity",
    short: "How much the company owes compared with the shareholders' money in it.",
    read: "Higher means more borrowing, which raises risk when profits fall. Banks and utilities normally carry much more debt than others.",
    good: "A rule of thumb: compare it with the sector, as normal levels differ a lot.",
  },
  dividend_yield: {
    term: "Dividend yield",
    short: "The yearly dividend as a percentage of the share price.",
    read: "It is the cash income if the dividend stays the same. A very high yield can mean the price has fallen because the dividend is at risk.",
  },
  market_cap: {
    term: "Market cap",
    short: "The share price times the number of shares: what the market values the whole company at.",
    read: "It measures size, not quality. Larger companies tend to move more slowly than small ones.",
  },
  week_range_52: {
    term: "52-week range",
    short: "The lowest and highest prices over the past year.",
    read: "Where the price sits in it shows whether it is near a yearly low or high. It describes the past, not what comes next.",
  },

  // Marketplace
  high_water_mark: {
    term: "High-water mark",
    short: "The highest account value on which a performance fee has already been paid.",
    read: "The creator earns a fee only on profit above this mark, so you don't pay twice for recovering a loss.",
  },
  performance_fee: {
    term: "Performance fee",
    short: "A share of the profit a strategy earns that goes to its creator.",
    read: "It is taken only on realized profit above the high-water mark, and nothing is taken if there is no new profit.",
  },
  version: {
    term: "Version",
    short: "One published release of a strategy's code.",
    read: "Subscribers stay on the version they joined and move to a newer one only when they choose to.",
  },
  subscription: {
    term: "Subscription",
    short: "Running a marketplace strategy with your own money in its own account.",
    read: "Stopping it closes its positions and returns the cash to your main account.",
  },

  // Badges
  badge: {
    term: "Badge",
    short: "A reward for good habits and for exploring: protecting trades, trying new markets, building and sharing algorithms.",
    read: "Badges come from live paper trades (and a few from finished sims or backtests, where the badge says so). They are never taken away.",
  },
  region: {
    term: "Region",
    short: "A set of eight badges for one group of markets: Kanto is India, Johto the US, Hoenn crypto and Sinnoh everywhere else.",
    read: "Each region rewards the same habits in its own markets, ending with a capstone for steady, profitable trading.",
  },
  elite_four: {
    term: "Elite Four",
    short: "Four badges for creators: a measured listing, subscribers, consistent results and new versions people upgrade to.",
    read: "They show on your marketplace cards, so subscribers can see a creator has a track record.",
  },
  champion: {
    term: "Champion",
    short: "The top title: all eight badges of any one region and all four Elite Four badges.",
    read: "It shows beside your name on the marketplace.",
  },

  // Sim
  replay: {
    term: "Replay",
    short: "Stepping through past prices bar by bar as if they were happening now.",
    read: "It lets you practise trading and test strategies without waiting for real time.",
  },
  speed: {
    term: "Speed (bars/s)",
    short: "How many bars of history the replay moves forward each second.",
    read: "Higher is faster. With daily candles, 5 bars a second is about a week of trading each second.",
  },
} satisfies Record<string, GlossaryEntry>;

export type TermId = keyof typeof GLOSSARY;
