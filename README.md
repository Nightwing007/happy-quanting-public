# Happy Quanting

Happy Quanting is a paper-trading playground that models what trading really costs: brokerage, taxes, exchange and regulatory fees, depository charges and currency conversion, on 35 markets and 13 brokers. It follows the real rules where it can: market hours, per-lot trades, short selling that differs by market, and stop-losses that fire at the market price rather than the price you set. On top of that engine sit a virtual sim that replays past days, a backtester that charges every fill, a code editor and a no-code block editor for algorithms, and a marketplace where creators sell algorithms without ever handing over their code. The backend is FastAPI with SQLite and the frontend is Next.js.

**Paper trading only. No real money is involved, and nothing here is financial advice.**

## Running it

Requirements: Node.js and npm, and Python 3 on Windows through the `py -3` launcher (the app is developed and run on Windows).

```
npm run setup   # installs both sides, creates backend\.venv with py -3
npm run dev     # API (port 8000) and web server side by side
npm test        # backend pytest (offline, no network)
npm run lint    # ruff, then eslint
```

Quiet variants that print only failures and a summary line: `npm run -s test:q` (backend tests, run in parallel), `npm run -s lint:q` (ruff and eslint), and `npm run -s e2e` (Playwright browser tests on a private stack, ports 8040 and 3040, with a fresh database; today they cover sign-up, log-in and user isolation).

On first start the server prints a one-time `Demo login: demo / <password>` line for the seeded `demo` account. Or just sign up at `/signup`.

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

## Accounts

Sign up with a username and password (`/signup`), log in at `/login`, edit your display name and bio on `/profile`. Passwords are stored as scrypt hashes and the session cookie (`hq_session`) is stored server-side only as a hash. Everything you create (orders, trades, sims, backtests, saved algorithms, subscriptions) belongs to you: someone else's id answers 404. Any expired session sends you to the login page. The five marketplace creators are demo personas with no password; nobody can log in as them.

## Virtual sim

`/sim` replays a past day (or range) through the same engine that handles live trades, at a speed you choose (1 to 200 bars per second), with 1-, 5- or 15-minute bars. The market data provider is wrapped so it can only show bars that have ended, so there is no look-ahead. Play, pause, step 1 or 10 bars, change the speed, reset; a progress bar and the exchange's own clock show where you are. Orders, charges, stop-losses, targets and the 15:20 square-off of Indian intraday shorts all behave as they do live. A sim session can also run an algorithm (a ready-made one, one of yours, or a marketplace listing, whose code and log stay hidden) while you watch, and you can trade by hand beside it.

## Algorithms

- **Five ready-made algorithms:** SMA crossover, RSI mean reversion, Bollinger band reversion, Donchian breakout and Crypto volatility breakout. Every one is a plain strategy class using the same `ctx` API available to your own code, and orders go through the same engine and charge tables as manual trades.
- **The lab** (`/algos/lab`): pick an algorithm, edit its settings, choose symbols, brokers, starting cash and exact first and last days, and run a backtest.
- **The backtester:** history is loaded for the exact window you pick, plus extra *warmup* bars before it so indicators are ready on day one (nothing is ever traded before the start). A decision on a bar fills at the **next** bar's price, never the one it was made on. Every fill pays the real charges for its market and broker, and the results page puts charges up front (total paid, and charges as a share of gross profit) before any return figure. The strategy is compared with an equal-weight buy-and-hold of the same symbols, charged the same way. Metrics are total return, CAGR (only over a year or more), max drawdown, Sharpe, win rate, profit factor, trades and exposure. Backtests run on a background worker and appear under Backtest history.
- **My algorithms:** save a tuned algorithm, code or block graph under your name, and reopen it in the lab, editor or block editor.
- **The code editor** (`/algos/editor`): Monaco, bundled so it works offline, with `ctx.` autocomplete, the code rules checked as you type (errors appear as markers), backtest, run in the sim, save and publish.
- **The block editor** (`/algos/blocks`): build a strategy without code on a canvas (React Flow). Big blocks are Symbols & interval (the Universe block), signals such as RSI below, SMA crossover, N-bar breakout, Bollinger touch, volume spike and price against an SMA, Combine (All of / Any of / Not), actions (Buy % of cash, Short % of cash, Sell all, Exit all trades), and risk blocks (Stop-loss %, Target %, Max open trades, Trading-hours window) that hang off an action. Three templates to start from (RSI dip-buyer, SMA trend follower, Breakout with stop). You can make your own blocks: a *group* of existing blocks, or a *code block* written in Python under the same code rules. The graph compiles to ordinary strategy source, which is shown under View code and checked by the same validator as uploaded code, so a block algorithm is as auditable as a hand-written one. Problems are marked on the node that causes them.

## Marketplace

Creators publish an algorithm; others subscribe to it and it trades for them.

- **Code and settings never leave the server.** The public views of a listing carry only its name, description, markets, fee, version numbers and changelogs, and measured performance. A test walks the API schemas and scans responses for the words that would give code away. Only the owner's own `/mine` views contain code.
- **Performance is computed by the server,** by backtesting the listing over the last 3 months, 1 year and 3 years on the creator's chosen symbols with the default brokers and starting cash, after real charges. The creator cannot upload their own numbers. Only totals and curves are stored, not trades. A window with too little history says "unavailable".
- **The creator's fee is a percentage of net realized profit above a high-water mark.** Profit is after all charges and financing, unrealized gains are never charged, and a loss followed by a recovery to the old level is never charged twice. The percentage is copied when you subscribe, so later edits do not change what you agreed to.
- **Subscribing** moves the capital you pick out of your live account into a separate account the algorithm trades; stopping exits its positions through the engine and returns what is left, less fees. A background loop steps each subscription once per closed bar.
- **Subscribers are pinned to a version.** A creator can publish new versions; you stay on yours until you opt in with Upgrade on your subscription.
- **The five demo creators** (Pokémon personas, seeded at startup): Zangoose (hourly momentum breakout), Slowking (weekly trend follower), Shuckle (uptrend dip buyer), Sharpedo (oversold ambush) and Electrode (crypto ATR breakout). Their strategies are real uploaded code running in the sandbox. The creator pages are at `/creators/<name>`; you create and manage your own listings at `/create`.

## Code rules and sandbox

Uploaded and editor code must follow the rules in [`docs/algo-rules.md`](docs/algo-rules.md): an allow-list of syntax, a short list of imports, no names starting with an underscore, a literal `warmup_bars`, and limits on source size, log output, time and memory. The checker reads the code's syntax tree and never runs it first. It then runs in a separate child process with limits (2 CPU seconds per hook, 30 seconds per run, 256 MB), and the engine stays in the parent: the code only sends requests.

**Be plain about what this is: the sandbox is fine on your own machine and is not safe for a public site.** It is a spawned process with time and memory limits, not a container or a locked-down user, and on Windows memory is enforced by polling. Do not expose upload to strangers until it runs somewhere properly isolated.

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

**Some figures could not be confirmed, and the code says so.** `grep -rn UNVERIFIED backend/app` finds 23 marks: 7 in `markets.py`, 3 in `brokers.py` and 13 in `metrics.py`. By category:

- *Market taxes and fees (7; two are the module's own docstring and a section comment):* Singapore's clearing-fee cap (the current SGX page could not be read), whether South Africa's securities transfer tax applies to ETF units, Belgium's stock-exchange tax for clients of foreign brokers, and the markets where no transaction tax was found and none is charged (Germany, Japan, Canada, Australia, the Netherlands and others), since no authority publishes a list of taxes it lacks.
- *Broker fees (3; one of them is the module's own docstring):* Dhan's two quoted intraday rules and INDmoney's GST rate.
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

## Known gaps

- **The sandbox is not a security boundary for a public site** (see above). Its limits are 2 CPU seconds per hook, 30 seconds and 256 MB per run, 50 KB of source, and a literal `warmup_bars` of at most 1000. The memory limit on Windows is a polled check, and the POSIX path is untested on this machine.
- **Yahoo history is short for small bars,** and the sim and the backtester refuse earlier dates and say what the earliest is: about 30 days for 1-minute bars (fetched in 7-day pieces), about 60 days for 5-, 15- and 30-minute bars, about 730 days for hourly, and no limit for daily, weekly and monthly. This is why the marketplace's "intraday" demo strategies use hourly bars.
- **Pokémon artwork and Yahoo data must both be replaced before any public launch.** Creator avatars are loaded at runtime from PokeAPI and never committed; the prices come from an unofficial, delayed feed for personal use.
- **The trading-hours block uses a fixed UTC offset** that you type in minutes, because strategy code has no exchange time zone. It does not follow clock changes, and it needs intraday bars.
- **The block editor has no undo.** Delete a block and it is gone (you can reload a template or re-add it).
- **Block algorithms and the marketplace are paper trading as well.** Subscriptions trade on delayed prices with the same charges and no spread or slippage, so published performance is optimistic by that much.
- **Tests:** the browser tests (Playwright) cover only accounts so far; the rest of the UI is checked by hand and by the type checker.

## API

Every route the app serves (78), generated from its OpenAPI schema (`backend/scripts/export_openapi.py`). Symbols always travel in query parameters, never in the path, because Yahoo symbols contain `^`, `=` and `.`. All routes need a logged-in user except health, `/api/market/*`, `/api/brokers`, `/api/algos/library`, `/api/algos/rules` and signup/login/logout. The sim routes mirror the live trading routes under `/api/sim/sessions/{session_id}`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server status, data source and account currency |
| POST | `/api/auth/signup` | Create an account and log in |
| POST | `/api/auth/login` | Log in (sets the session cookie) |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/me` | The logged-in user |
| PUT | `/api/me` | Change display name, bio and avatar |
| GET | `/api/market/search` | Search instruments by name or symbol (`q`) |
| GET | `/api/market/quote` | Latest price, day change and market status for a `symbol` |
| GET | `/api/market/bars` | Candles for a `symbol`, `interval` and `range`, with optional indicators |
| GET | `/api/market/metrics` | Company metrics against sector ranges (a coin's own figures for crypto) |
| GET | `/api/market/history-limits` | The earliest date available for each bar size |
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
| GET | `/api/sim/sessions` | Your simulations |
| POST | `/api/sim/sessions` | Start a simulation (symbols, bar size, days, speed, optional strategy) |
| GET | `/api/sim/sessions/{session_id}` | The session's state, cursor and strategy log |
| DELETE | `/api/sim/sessions/{session_id}` | Delete a session |
| POST | `/api/sim/sessions/{session_id}/control` | Start, pause, step, change speed or reset |
| GET | `/api/sim/sessions/{session_id}/portfolio` | The session's portfolio |
| GET | `/api/sim/sessions/{session_id}/orders` | The session's orders |
| POST | `/api/sim/sessions/{session_id}/orders` | Place an order in the session |
| POST | `/api/sim/sessions/{session_id}/orders/preview` | Preview an order in the session |
| DELETE | `/api/sim/sessions/{session_id}/orders/{order_id}` | Cancel a waiting order in the session |
| GET | `/api/sim/sessions/{session_id}/trades` | The session's trades |
| GET | `/api/sim/sessions/{session_id}/payouts` | The session's closed trades |
| POST | `/api/sim/sessions/{session_id}/trades/{trade_id}/exit` | Exit a trade in the session |
| POST | `/api/sim/sessions/{session_id}/trades/{trade_id}/exit/preview` | Preview that exit |
| PUT | `/api/sim/sessions/{session_id}/trades/{trade_id}/protection` | Set a stop-loss and target in the session |
| POST | `/api/sim/sessions/{session_id}/trades/{trade_id}/protection/preview` | Preview protection in the session |
| GET | `/api/algos/library` | The five ready-made algorithms |
| GET | `/api/algos/rules` | The code rules and their numbers (public) |
| POST | `/api/algos/validate` | Check strategy code against the rules; nothing is saved |
| GET | `/api/algos/mine` | Your saved algorithms |
| POST | `/api/algos/mine` | Save an algorithm (library settings, code or a block graph) |
| GET | `/api/algos/mine/{algo_id}` | One saved algorithm (code and graph only for its owner) |
| PUT | `/api/algos/mine/{algo_id}` | Update a saved algorithm |
| DELETE | `/api/algos/mine/{algo_id}` | Delete a saved algorithm |
| GET | `/api/blocks/catalog` | Every block: ports, settings, help |
| POST | `/api/blocks/compile` | Check a block graph and compile it to strategy source |
| GET | `/api/blocks/custom` | Your custom blocks |
| POST | `/api/blocks/custom` | Make a custom block (group or code) |
| GET | `/api/blocks/custom/{block_id}` | One custom block |
| PUT | `/api/blocks/custom/{block_id}` | Update a custom block |
| DELETE | `/api/blocks/custom/{block_id}` | Delete a custom block |
| GET | `/api/backtests` | Your backtests |
| POST | `/api/backtests` | Queue a backtest (library, saved algorithm or source) |
| GET | `/api/backtests/{backtest_id}` | A backtest's status and results |
| DELETE | `/api/backtests/{backtest_id}` | Delete a backtest |
| GET | `/api/marketplace/listings` | Published listings with measured performance (`?creator=` filter) |
| POST | `/api/marketplace/listings` | Create a draft listing |
| GET | `/api/marketplace/listings/{listing_id}` | One listing, public view |
| PUT | `/api/marketplace/listings/{listing_id}` | Edit a listing or add a version |
| POST | `/api/marketplace/listings/{listing_id}/publish` | Publish a listing |
| POST | `/api/marketplace/listings/{listing_id}/retire` | Retire a listing |
| POST | `/api/marketplace/listings/{listing_id}/refresh-performance` | Re-measure performance |
| POST | `/api/marketplace/listings/{listing_id}/subscribe` | Subscribe with capital from your live cash |
| GET | `/api/marketplace/creators/{username}` | A creator's profile and listings |
| GET | `/api/marketplace/mine` | Your own listings (the only view with code and settings) |
| GET | `/api/marketplace/subscriptions` | Your subscriptions |
| POST | `/api/marketplace/subscriptions/{subscription_id}/stop` | Stop a subscription and return the cash |
| POST | `/api/marketplace/subscriptions/{subscription_id}/upgrade` | Move to the listing's newer version |
| GET | `/api/marketplace/earnings` | Fees you have earned as a creator |

Trading errors come back as HTTP 400 with `{"detail": "<a sentence for people>", "code": "<stable_name>"}`. Match on `code`, never on the sentence.

## Project layout

```
package.json               npm scripts: setup, dev, test, test:q, lint, lint:q, check:web, build:web, e2e
docs/ARCHITECTURE.md       map of the code
docs/algo-rules.md         the rules uploaded and editor code must follow
docs/ROADMAP.md            what was built and what comes next
backend/
  dev.py                   dev server (uvicorn under watchfiles; never uvicorn --reload on Windows)
  app/
    main.py                FastAPI app, error handlers, lifespan and the background loops
    clock.py               the one clock all trading code reads
    config.py, db.py       settings from backend/.env; SQLAlchemy base and the Decimal-as-text column
    auth.py                password hashing, sessions, login limiter
    models.py              all tables
    schemas.py             Pydantic API models (money as strings; also the shape stored in JSON)
    metrics.py, indicators.py  company metrics and sector ranges; SMA, EMA, RSI and friends
    migrate.py             runs Alembic migrations at startup
    api/                   routes: auth, market, trading, settings, watchlist, sim, algos, blocks, backtests, marketplace
    market_data/           the provider interface, Yahoo (only place yfinance is imported), an offline fake, caches, history and replay
    trading/               engine, per-market and per-broker charge tables, fees calculator, market hours, errors
    sim/                   virtual sim: runner, driver loop, strategy runs
    algos/                 strategy API, library (5 algorithms), backtester, validator, sandbox, rules
    algos/blocks/          block catalog, graph validator and compiler, custom blocks
    marketplace/           listings, versions, performance, subscriptions, live runs, demo seed
  seed/algos/              the five demo creators' strategy code
  migrations/versions/     0001 to 0017
  tests/                   offline pytest suite
  scripts/                 export_openapi.py, qtest.py, seed_marketplace.py
frontend/
  src/app/                 pages: dashboard, trade, sim, algos (lab, editor, blocks, backtests), marketplace, creators, create, orders, payouts, settings, login, signup, profile
  src/components/          UI by page area; ui/ is shadcn (base-nova on @base-ui/react)
  src/lib/                 api.ts and queries.ts (TanStack Query), format.ts (the only place decimal strings become numbers), generated api-types.ts
  e2e/                     Playwright browser tests
```

## Data source

Prices come from Yahoo Finance through `yfinance`: free, delayed, unofficial, and for personal use only. It sits behind a `MarketDataProvider` interface (`backend/app/market_data/base.py`) and nothing else imports `yfinance`, so it can be replaced with a licensed feed or a broker API before this is ever deployed publicly. Tests and `MARKET_DATA_PROVIDER=fake` use an offline provider with fixed prices.
