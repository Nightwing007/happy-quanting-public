# Features

Everything Happy Quanting does, page by page. The rules behind it are in [TRADING-RULES.md](TRADING-RULES.md), the charge tables in [CHARGES.md](CHARGES.md), the routes in [API.md](API.md).

Navigation: **Dashboard · Trade · Sim · HFT**. HFT opens three sections: Algo (algorithms, lab, backtest history, deployments), Market (marketplace, your subscriptions, creator earnings) and Create (code editor, block editor, upload, your listings). Orders, Payouts, Settings, Profile and Badges are in the profile menu. Search is on Ctrl+K.

## What works

- **Search and charts.** Search Yahoo Finance for stocks, ETFs and crypto worldwide. Candlestick charts from 1 day to max, with volume, SMA 20 and 50, EMA 20 and RSI 14. `/trade` without a symbol shows markets, your watchlist, popular and recently viewed symbols.
- **An INR account.** Rs 10,00,000 to start. Other currencies are converted at the live rate, with the broker's markup where it has one.
- **Orders.** Market and limit orders, buys and sells, with a preview before you commit that shows every charge line from the same calculation that later charges it. Fractions where the market allows them. Waiting orders can be cancelled.
- **Costs on every trade,** itemised and explained on hover.
- **Market hours.** Real exchange calendars; crypto never closes.
- **Per-lot trades.** Every fill that opens a position is its own trade with its own entry price, charges and profit, exited on its own or in part.
- **Short selling** with each market's real regime.
- **Stop-loss and target** on any open trade, with a preview of what each would leave you with after charges, drawn on the chart.
- **Chart overlays.** Your average entry price, break-even price (exit charges included), stop and target lines, and Buy/Sell/Short/Cover arrows.
- **Company metrics** on stock pages: P/E, price-to-book, return on equity, debt-to-equity and dividend yield against a sector range, each explained on hover. Coins get market cap, 24-hour volume, circulating supply and their position in the 52-week range.
- **Dashboard.** Cash, margin used, available cash, total value, realized and unrealized P&L, pooled holdings, open trades with an Exit button each, a charges-paid breakdown by category, a watchlist, and a card for your running deployments.
- **Orders page** (profile menu). The history says what each order really did, for example "Sell 8: closed 5 of trade #3, opened short #7 (3)". Reset account lives there.
- **Payouts page** (profile menu). Every closed trade: what the exit brought in, the charges at both ends line by line, any borrowing or funding cost, the profit left over, and a badge for how it ended (Exited, Stop-loss fired, Target reached, Squared off by broker).
- **Settings** (profile menu). Pick a broker for Indian stocks, international stocks and crypto.
- **Glossary tooltips.** Trading and finance terms (stop-loss, STT, drawdown, Sharpe, high-water mark and many more) are explained on hover or tap, across the chart, order ticket, dashboard, results and marketplace.
- **Dark and light themes,** in a Thomso-inspired style (violet accent, split-flap headings, mono figures). Dark is the default; the toggle is in the header. Motion respects reduced-motion settings.

## Accounts

Sign up with a username and password (`/signup`), log in at `/login`, edit your display name and bio on `/profile`. Passwords are stored as scrypt hashes and the session cookie (`hq_session`) is stored server-side only as a hash. Everything you create (orders, trades, sims, backtests, saved algorithms, deployments, subscriptions) belongs to you: someone else's id answers 404. Any expired session sends you to the login page. The five marketplace creators are demo personas with no password; nobody can log in as them. On first start the server prints a one-time `Demo login: demo / <password>` line for a seeded `demo` account.

## Virtual sim

`/sim` replays a past day (or range) through the same engine that handles live trades, at a speed you choose (1 to 200 bars per second), with 1-, 5- or 15-minute bars. The market data provider is wrapped so it can only show bars that have ended, so there is no look-ahead. Play, pause, step 1 or 10 bars, change the speed, reset; a progress bar and the exchange's own clock show where you are. Orders, charges, stop-losses, targets and the 15:20 square-off of Indian intraday shorts all behave as they do live. A sim session can also run an algorithm (a ready-made one, one of yours, or a marketplace listing, whose code and log stay hidden) while you watch, and you can trade by hand beside it. Orders and chart arrows appear as the session plays; a finished sim refuses new orders.

## Algorithms

- **Five ready-made algorithms:** SMA crossover, RSI mean reversion, Bollinger band reversion, Donchian breakout and Crypto volatility breakout. Every one is a plain strategy class using the same `ctx` API available to your own code, and orders go through the same engine and charge tables as manual trades.
- **The lab** (`/algos/lab`): pick an algorithm, edit its settings, choose symbols, brokers, starting cash and exact first and last days, and run a backtest.
- **The backtester:** history is loaded for the exact window you pick, plus extra *warmup* bars before it so indicators are ready on day one (nothing is ever traded before the start). A decision on a bar fills at the **next** bar's price, never the one it was made on. Every fill pays the real charges for its market and broker, and the results page puts charges up front (total paid, and charges as a share of gross profit) before any return figure. The strategy is compared with an equal-weight buy-and-hold of the same symbols, charged the same way. Metrics are total return, CAGR (only over a year or more), max drawdown, Sharpe, win rate, profit factor, trades, exposure and maximum position size. Backtests run on a background worker and appear under Backtest history (`/algos/backtests`).
- **My algorithms** (`/algos`): save a tuned algorithm, code or block graph under your name, and reopen it in the lab, the code editor or the block editor.
- **The code editor** (`/create/editor`): Monaco, bundled so it works offline, with `ctx.` autocomplete, the code rules checked as you type (errors appear as markers), backtest, run in the sim, save and publish.
- **The block editor** (`/create/blocks`): build a strategy without code on a canvas (React Flow). Big blocks are Symbols & interval (the Universe block), signals such as RSI below, SMA crossover, N-bar breakout, Bollinger touch, volume spike and price against an SMA, Combine (All of / Any of / Not), actions (Buy % of cash, Short % of cash, Sell all, Exit all trades), and risk blocks (Stop-loss %, Target %, Max open trades, Trading-hours window) that hang off an action. Three templates to start from (RSI dip-buyer, SMA trend follower, Breakout with stop). You can make your own blocks: a *group* of existing blocks, or a *code block* written in Python under the same code rules. The graph compiles to ordinary strategy source, which is shown under View code and checked by the same validator as uploaded code, so a block algorithm is as auditable as a hand-written one. Problems are marked on the node that causes them.
- **Deployments** (`/deployments`): deploy one of your own algorithms (a ready-made one with tuned settings, or a saved one) to trade live on its own paper sub-account, funded from your cash. The Deploy dialog is in the lab, My algorithms, the results page and, after saving, both editors. Each deployment has a status lamp, a ledger, its trades and orders, and a live log. Pause keeps positions and their stops; Stop exits through the engine and returns the cash. The algorithm is pinned as it was when you deployed it.

## Marketplace

Creators publish an algorithm; others subscribe to it and it trades for them.

- **Code and settings never leave the server.** The public views of a listing carry only its name, description, markets, fee, version numbers and changelogs, and measured performance. A test walks the API schemas and scans responses for the words that would give code away. Only the owner's own `/mine` views contain code.
- **Performance is computed by the server,** by backtesting the listing over the last 3 months, 1 year and 3 years on the creator's chosen symbols with the default brokers and starting cash, after real charges. The creator cannot upload their own numbers. Only totals and curves are stored, not trades. A window with too little history says "unavailable".
- **The creator's fee is a percentage of net realized profit above a high-water mark.** Profit is after all charges and financing, unrealized gains are never charged, and a loss followed by a recovery to the old level is never charged twice. The percentage is copied when you subscribe, so later edits do not change what you agreed to.
- **Subscribing** moves the capital you pick out of your live account into a separate account the algorithm trades; stopping exits its positions through the engine and returns what is left, less fees. A background loop steps each subscription once per closed bar.
- **Subscribers are pinned to a version.** A creator can publish new versions; you stay on yours until you opt in with Upgrade on your subscription.
- **Creators** have a public page at `/creators/<name>` and manage their listings at `/create` (version, status, performance, retire, publish, new version). Fees earned are on `/marketplace/earnings`.
- **The five demo creators** (Pokémon personas, seeded at startup): Zangoose (hourly momentum breakout), Slowking (weekly trend follower), Shuckle (uptrend dip buyer), Sharpedo (oversold ambush) and Electrode (crypto ATR breakout). Their strategies are real uploaded code running in the sandbox.

## Badges

`/badges` is a gym-badge case for disciplined trading, in four regions plus the Elite Four and the Champion: Kanto (Indian markets), Johto (US), Hoenn (crypto), Sinnoh (global), the Elite Four (Debut, Trusted, Consistent, Craftsman) and the Champion badge. Badges are computed from your live-account trades, finished sims, crypto backtests and marketplace activity, are never revoked, and are awarded by a background sweep. A toast announces each new badge once. The case is also on your profile and on creator pages; creators' Elite Four badges show on their marketplace cards. Trades made inside deployments and subscriptions do not count.

## Code rules and sandbox

Uploaded and editor code must follow the rules in [`algo-rules.md`](algo-rules.md): an allow-list of syntax, a short list of imports, no names starting with an underscore, a literal `warmup_bars`, and limits on source size, log output, time and memory. The checker reads the code's syntax tree and never runs it first. It then runs in a separate child process with limits (2 CPU seconds per hook, 30 seconds per run, 256 MB), and the engine stays in the parent: the code only sends requests.

**Be plain about what this is: the sandbox is fine on your own machine and is not safe for a public site.** It is a spawned process with time and memory limits, not a container or a locked-down user, and on Windows memory is enforced by polling.

**Hosted mode.** With `HOSTED_MODE=true` the server refuses every way of bringing code (validating, saving source, code blocks, and source backtests, sims, deployments and listings), caps the number of sandbox processes, and reports `hosted_mode` on `/api/health`. The frontend then hides the code editor, upload and code blocks and shows a note. Ready-made algorithms, the lab, block graphs without code blocks and the seeded marketplace listings all keep working. See [DEPLOY.md](DEPLOY.md).
