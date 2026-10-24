# Happy Quanting

Happy Quanting is a paper-trading playground that models what trading really costs: brokerage, taxes, exchange and regulatory fees, depository charges and currency conversion, on 35 markets and 13 brokers. It follows the real rules where it can: market hours, per-lot trades, short selling that differs by market, and stop-losses that fire at the market price rather than the price you set. The backend is FastAPI with SQLite and the frontend is Next.js.

**Paper trading only. No real money is involved, and nothing here is financial advice.**

## Running it

Requirements: Node.js and npm, and Python 3 on Windows through the `py -3` launcher (the app is developed and run on Windows).

```
npm run setup   # installs both sides, creates backend\.venv with py -3
npm run dev     # API (port 8000) and web server side by side
npm test        # backend pytest (offline, no network)
npm run lint    # ruff, then eslint
```

Then open the web address printed in the `web` lines of the startup output. Port 3000 is often taken, so the web server may land on 3001; read the output rather than assuming.

Optional settings go in `backend/.env` (copy `backend/.env.example`): the account currency, the starting cash, and `MARKET_DATA_PROVIDER=fake` for deterministic offline prices. To run a second stack beside the first (say, against a scratch database), set `PORT` for the backend (`backend/dev.py`, default 8000), `DATABASE_URL` for its database, and `BACKEND_URL` for the Next.js dev server so it forwards `/api` to the right port. Next's own port is `next dev -p <port>`.

## What works

- **Search and charts.** Search Yahoo Finance for stocks, ETFs and crypto worldwide (Ctrl+K). Candlestick charts from 1 day to max, with volume, SMA 20 and 50, EMA 20 and RSI 14.
- **An INR account.** Rs 10,00,000 to start. Instruments in other currencies are converted at the live exchange rate, with the broker's conversion markup where it has one.
- **Orders.** Market and limit orders, buys and sells, with a preview before you commit that shows every charge line from the same calculation that later charges it. Fractions where the market allows them (US shares to 4 decimals, crypto to 8). Waiting orders can be cancelled.
- **Costs on every trade.** Itemised and explained on hover: see "Where the charges come from".
- **Market hours.** Real exchange calendars with holidays, half days and lunch breaks. Crypto never closes.
- **Per-lot trades.** Every fill that opens a position is its own trade with its own entry price, charges and profit, exited on its own or in part.
- **Short selling** with each market's real regime (below).
- **Stop-loss and target** on any open trade, with a preview of what each would leave you with after charges, drawn on the chart.
- **Chart overlays.** Your average entry price, break-even price (exit charges included), stop and target lines, and Buy/Sell/Short/Cover arrows. The price scale widens to keep those lines visible.
- **Company metrics** on stock pages: P/E, price-to-book, return on equity, debt-to-equity and dividend yield against a sector range, each explained on hover. Coins get market cap, 24-hour volume, circulating supply and their position in the 52-week range, with no sector band.
- **Dashboard.** Cash, margin used, available cash, total value, realized and unrealized P&L, pooled holdings, open trades with an Exit button each, a charges-paid breakdown by category, and a watchlist.
- **Orders page.** The history says what each order really did, for example "Sell 8: closed 5 of trade #3, opened short #7 (3)". Reset account lives there.
- **Payouts page.** Every closed trade: what the exit brought in, the charges at both ends line by line, any borrowing or funding cost, the profit left over, and a badge for how it ended (Exited, Stop-loss fired, Target reached, Squared off by broker).
- **Settings.** Pick a broker for Indian stocks, international stocks and crypto; the choice changes the charges and which markets you can trade.

A background loop runs every 60 seconds while the server is up. It fills limit orders and orders that waited for the open, fires stop-losses and targets, squares off Indian intraday shorts, and charges borrow and funding. Nothing happens while the server is off, and it catches up on borrow and funding when it returns.

## The paper-trading rules

- **Money.** The account is in INR and starts with Rs 10,00,000. Every trade pays its real costs; there is no zero-cost mode.
- **Market hours and waiting orders.** An order placed while its market is closed is accepted and waits for the open, like an after-market order (AMO), and fills at the first fresh quote of the session. A waiting order does not reserve cash: it is checked when placed and again when it fills. Orders fill only against a quote from the current session, so an old closing price right after an open is never used. An Indian intraday short cannot wait (see below).
- **Limit orders.** A limit order fills when the market reaches its price, and it fills at the market price at that moment, not at the limit. A limit order that rested before being hit is charged as a maker where the market has maker rates.
- **Per-lot trades.** Buying twice gives two trades. How you exit depends on the market, as in real life: **US and crypto** let you name the lot you are exiting (specific-lot identification); **India and every other market** pool holdings, so an exit takes the oldest lot first (FIFO) whichever trade you started it from, and the app says so. Holdings on the dashboard are computed from the open trades.
- **Selling reads the way a broker reads it.** One sell closes your open buys first, oldest first, and only the remainder becomes a short. Sell 8 holding 5 and you close 5 and short 3, charged as two separate contracts under different products.
- **Shorting, per market.**
  - *India (NSE, BSE):* intraday only. 20% of the value is blocked as margin (the proceeds are not paid out), there is no borrow fee, and whatever is still open 10 minutes before the close is bought back for you ("Squared off by broker"). It is charged with the intraday tables (different STT and stamp duty, no depository charge) and cannot be placed while the market is closed.
  - *US:* may be held overnight. 50% margin (Reg T), roughly 3% a year borrow charged daily on the entry value, whole shares only.
  - *Crypto:* held as long as you like on 20% margin (5x), with funding of 0.01% every 8 hours (10.95% a year) charged on the entry value.
  - *Everywhere else:* shorting is not offered, as for most retail accounts.
- **Margin, not proceeds; cash never negative.** A short blocks margin out of your cash. Available cash is cash less margin used and can never go below zero; an order that would take it there is refused.
- **Stop-loss and target.** Attached to a trade, not an order type. Set one or both: whichever price is reached first closes the trade's whole open part and the other stops applying, like a broker's one-cancels-other GTT. It fills **at the market price**, not at the price you set, so a gap through your stop gets you out lower. If one price is crossed by a gap past both, the stop wins. It lapses after a year, like a GTT. It is only watched while the market is open, against a fresh quote. There is no trailing stop.
- **No profit taxes, deliberately.** No capital-gains tax and no 1% crypto TDS. The project teaches transaction costs, which are paid whether you win or lose, and mixing in profit taxes would blur that. (Transaction taxes such as STT, stamp duty and the European financial transaction taxes are charged.)

## Where the charges come from

Charges are data, not code. Every rate sits in a plain table with its source URL and the date it was checked, so it can be corrected without touching any logic:

- `backend/app/trading/markets.py` holds the taxes and exchange fees every trade on an exchange pays, whoever the broker is.
- `backend/app/trading/brokers.py` holds what each broker adds: brokerage, depository charges and currency-conversion markup.
- `backend/app/trading/fees.py` is the one calculator that applies them. Charges are rounded line by line to two decimals, as a contract note is.

**Markets (35):** NSE, BSE, US, London, Dublin, Paris, Milan, Madrid, Hong Kong, Singapore, Seoul (KOSPI and KOSDAQ), Taiwan (TWSE and OTC), Shanghai, Shenzhen, Johannesburg, crypto, Germany (Xetra), Frankfurt, Tokyo, Toronto (and Toronto Venture), Australia, Amsterdam, Switzerland, Brussels, Vienna, Lisbon, Stockholm, Oslo, Copenhagen, Helsinki, New Zealand and Mexico. A symbol on any other exchange is refused rather than priced as American. All rates were last checked on 2026-10-24.

**Brokers (13):**

| Segment | Brokers |
| --- | --- |
| Indian stocks | Zerodha, Groww (default), Upstox, Angel One, Dhan |
| International stocks | Interactive Brokers (default), INDmoney, Vested |
| Crypto | CoinDCX (default), CoinSwitch, WazirX, Mudrex, Binance |

**Some figures could not be confirmed, and the code says so.** `grep -rn UNVERIFIED backend/app` finds 40 marks: 22 in `markets.py`, 5 in `brokers.py` and 13 in `metrics.py`. By category:

- *Market taxes and fees (22):* whether ETFs are exempt from India's STT and from several markets' stamp duties and transaction taxes (they are simply not charged), the Hong Kong CCASS settlement fee (not modelled), Singapore's clearing-fee cap and GST rate, Taiwan's OTC rates (assumed the same as the main board), small China exchange fees and South Africa's JSE and Strate fees (not recorded), and several European markets where no transaction tax could be confirmed and none is charged (Germany, Switzerland, Belgium, Finland and others).
- *Broker fees (5; one of them is the module's own docstring):* Upstox's low-value brokerage cap and intraday minimum, Dhan's two quoted intraday rules, and INDmoney's GST rate.
- *Company-metric ranges (13):* the dividend-yield bands for every sector (the other four metrics are sourced to Damodaran's NYU Stern datasets of January 2026).

Some figures were checked on 2026-09-15 and have **not been re-verified** since; they are marked as such in the code: INDmoney's currency-conversion markup (0.7%), Vested's (1%), CoinSwitch's fees (0.1% taker, 0% maker, + 18% GST), WazirX's fees (0.2% + 18% GST; its Rs 99 a month no-fee plan is not modelled), and the roughly 1% cost of converting rupees to USDT that CoinDCX, CoinSwitch, WazirX and Mudrex add when you buy a coin priced in dollars from a rupee account. Binance gets no such cost: there is no sourced figure for how an Indian user funds it.

## What is deliberately not modelled

The honest part. If a cost or rule is not on the list above, assume it is missing.

- **No bid/ask spread.** Often the largest real cost on a retail trade. Orders fill at the quote's single price.
- **Delayed prices** (roughly 15 minutes from Yahoo), so there is no order-book simulation and stop-losses and targets fire late, against a price that is already old.
- **No market impact or slippage.** A large order fills at the same price as a small one.
- **A flat borrow rate** (3% a year in the US) instead of per-stock rates; hard-to-borrow shorts cost far more in reality.
- **No leverage on buys.** Buys need the full amount. Intraday margin on purchases is deliberately left out; it makes it too easy to blow up an account while learning.
- **No T+1 settlement** and **no circuit limits** (price bands that halt trading).
- **No capital-gains tax and no crypto TDS** (see above), and no bank charges for sending money abroad under India's LRS.
- **Exchange calendars have limits.** Indian holidays are only known about a year ahead; past that the market status is "unknown" and trading is allowed rather than refused.
- **Simplifications in the charge tables:**
  - The depository (DP) charge is applied to every sell order; in reality it is once per share per day, so two sells of the same share in a day pay it twice here.
  - The French, Italian and Spanish financial transaction taxes are applied to every listed share, though they really apply only to companies above a market-value threshold.
  - UK stamp duty is applied to every UK share, though AIM and some foreign companies are exempt.
  - Local sales taxes on commissions (other than India's GST) are not modelled, nor are volume tiers (Mudrex's cheaper tiers, for example) or introductory offers.
- **The sector ranges for company metrics are hand-written rules of thumb**, not a live feed. Yahoo publishes no sector benchmarks, and the card says so.
- **Single account, no logins.**

## API

Every route the app serves (23), generated from its OpenAPI schema. Symbols always travel in query parameters, never in the path, because Yahoo symbols contain `^`, `=` and `.`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server status, data source and account currency |
| GET | `/api/market/search` | Search instruments by name or symbol (`q`) |
| GET | `/api/market/quote` | Latest price, day change and market status for a `symbol` |
| GET | `/api/market/bars` | Candles for a `symbol`, `interval` and `range`, with optional indicators |
| GET | `/api/market/metrics` | Company metrics against sector ranges (a coin's own figures for crypto) |
| GET | `/api/portfolio` | Cash, margin, value, P&L, charges paid, pooled holdings and open trades |
| POST | `/api/portfolio/reset` | Delete orders and trades and restore the starting cash (the watchlist is kept) |
| GET | `/api/orders` | Order history, newest first (`status`, `symbol`, `limit`) |
| POST | `/api/orders` | Place a buy or sell, market or limit |
| POST | `/api/orders/preview` | What an order would cost, from the calculation that charges it, saving nothing |
| DELETE | `/api/orders/{order_id}` | Cancel a waiting order |
| GET | `/api/trades` | Trades with live figures for open ones (`status`, `symbol`, `limit`) |
| GET | `/api/payouts` | Closed trades with the charges at both ends line by line, and totals |
| POST | `/api/trades/{trade_id}/exit` | Exit all or part of a trade at the market |
| POST | `/api/trades/{trade_id}/exit/preview` | The payout of an exit before committing |
| PUT | `/api/trades/{trade_id}/protection` | Set or clear a trade's stop-loss and target |
| POST | `/api/trades/{trade_id}/protection/preview` | Check a stop-loss and target and show what each would leave you with |
| GET | `/api/settings` | The chosen broker for each segment |
| PUT | `/api/settings` | Change the chosen brokers |
| GET | `/api/brokers` | Every broker by segment, with its notes, markets and sources |
| GET | `/api/watchlist` | The watchlist with live prices |
| POST | `/api/watchlist` | Add a symbol |
| DELETE | `/api/watchlist` | Remove a symbol (`symbol`) |

Trading errors come back as HTTP 400 with `{"detail": "<a sentence for people>", "code": "<stable_name>"}`. Match on `code`, never on the sentence.

## Project layout

```
package.json               npm scripts: setup, dev, test, lint
docs/ROADMAP.md            what was built and what comes next
backend/
  dev.py                   dev server (uvicorn under watchfiles; never uvicorn --reload on Windows)
  app/
    main.py                FastAPI app, error handlers, the 60-second background loop
    clock.py               the one clock all trading code reads
    config.py, db.py       settings from backend/.env; SQLAlchemy base and the Decimal-as-text column
    models.py              the four tables: accounts, trades, orders, watchlist_items
    schemas.py             Pydantic API models (money as strings; also the shape stored in JSON)
    metrics.py             company metrics and the sector range tables
    indicators.py          SMA, EMA, RSI
    migrate.py             runs Alembic migrations at startup
    api/                   routes: market, trading, settings, watchlist
    market_data/           the provider interface, the Yahoo implementation (only place yfinance is imported), an offline fake, caches
    trading/
      engine.py            orders, fills, trades, shorts, protection, portfolio, payouts
      markets.py           per-market taxes, fees, shorting rules, lot rules (data)
      brokers.py           per-broker fees (data)
      fees.py              the fee shape and the one calculator
      hours.py             exchange calendars, open/closed, can_fill
      errors.py            trading errors, each with a stable code
  migrations/versions/     0001 to 0004
  tests/                   offline pytest suite
  scripts/export_openapi.py  writes openapi.json for the frontend types
frontend/
  src/app/                 pages: dashboard, trade, orders, payouts, settings
  src/components/          UI by page area; ui/ is shadcn (base-nova on @base-ui/react)
  src/lib/                 api.ts and queries.ts (TanStack Query), format.ts (the only place decimal strings become numbers), generated api-types.ts
```

## Data source

Prices come from Yahoo Finance through `yfinance`: free, delayed, unofficial, and for personal use only. It sits behind a `MarketDataProvider` interface (`backend/app/market_data/base.py`) and nothing else imports `yfinance`, so it can be replaced with a licensed feed or a broker API before this is ever deployed publicly. Tests and `MARKET_DATA_PROVIDER=fake` use an offline provider with fixed prices.
