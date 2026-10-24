# Roadmap

What was built, checked against the code on 2026-10-24, and what comes next.
Where something is only partly built, it says so.

## Milestone 1: charts and paper trading (built)

Legend: [x] built and working, [~] built with a stated gap.

- [x] Search stocks worldwide and crypto; candlestick charts from 1 day to max with volume, SMA 20 and 50, EMA 20 and RSI 14
- [x] Paper trading in rupees (Rs 10,00,000 to start): market and limit orders, buy, sell and short; fractions for US shares (4 decimals) and crypto (8)
- [x] Every fill that opens a position is its own trade. US and crypto exit a named lot; India and every other market pool holdings and exit oldest first
- [x] Short selling with each market's rules: margin blocked instead of proceeds paid, daily borrow (US) and 8-hourly funding (crypto), Indian intraday shorts squared off 10 minutes before the close
- [~] Five company metrics (P/E, price-to-book, ROE, debt-to-equity, dividend yield) explained on hover, against sector ranges. The first four are sourced to Damodaran's January 2026 data; **the dividend-yield bands are marked UNVERIFIED**. Coins get four metrics of their own with no sector band
- [x] Stop-loss and target on any trade as a one-cancels-other pair that fills at the market price and lapses after a year, drawn on the chart, with what each would pay shown before it is set
- [x] A payouts page: what every closed trade brought in, the charges at both ends line by line, borrowing or funding, the profit left, and how it closed
- [~] Real-world costs for 35 markets, shown before and after every trade (brokerage, taxes, exchange and regulatory fees, depository charges, GST, currency conversion). **7 market-table marks and 3 broker marks are UNVERIFIED** in the code, and a few more broker figures were checked on 2026-09-15 and not re-verified since
- [~] Pick your broker: Zerodha, Groww, Upstox, Angel One, Dhan; Interactive Brokers, INDmoney, Vested; CoinDCX, CoinSwitch, WazirX, Mudrex, Binance (13). CoinSwitch's and WazirX's fees, INDmoney's and Vested's conversion markups and the rupee-to-USDT cost on Indian crypto exchanges were checked on 2026-09-15 and are not re-verified
- [x] Real market hours and holidays from exchange calendars; orders placed while a market is closed wait for the open (like an AMO); crypto is 24/7
- [x] The chart shows your average entry price, break-even price, stop and target, and Buy/Sell/Short/Cover arrows; the price scale widens to keep the lines in view
- [x] Order history that names what each order did and the trades it touched
- [x] Prices from Yahoo Finance: free, delayed, personal use only

Known gaps, deliberately left out: no bid/ask spread, delayed prices, no market impact or slippage,
a flat borrow rate, no leverage on buys, no T+1 settlement, no circuit limits, no profit taxes. The
README lists these and the smaller simplifications in the charge tables.

## Next

- **Futures, options and forex** with leverage (US futures and options, spot forex). Indian F&O needs a broker data feed (Kite, Upstox). LRS does not let Indian residents trade leveraged products abroad, so this would be practice only.

## Later milestones

- **M2: Strategies.** Preset strategies (for example an SMA crossover), Python strategy code, and a backtester that reuses the indicators in `backend/app/indicators.py` and the order engine.
- **M3: Live paper strategies.** Run strategies on the paper account and track their performance.
- **M4: Accounts and deployment.** Logins, Postgres, hosting.
- **M5: Algorithm marketplace.** Needs sandboxed user code, and research into the rules for running strategies with other people's money.

## Ideas

- Capital gains tax and the 1% crypto TDS, if profit taxes are wanted after all
- Leverage on buys (intraday MIS margin), T+1 settlement, circuit limits
- Hard-to-borrow shorts that cost far more than the flat 3% a year used now
- A bid/ask spread and size-dependent slippage
- Bank charges for sending money abroad under LRS
- Confirming the UNVERIFIED rates, and re-verifying the figures last checked on 2026-09-15 (CoinSwitch, WazirX, INDmoney and Vested conversion, crypto rupee conversion)

## Before any public launch

- Replace Yahoo Finance with a licensed data feed or a broker API. The provider interface exists for exactly this.
