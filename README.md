# HAPPY QUANTING

**Gotta trade 'em all.**

A paper-trading playground that charges every brokerage, tax and fee a real trade pays, so what you learn survives contact with a real account.

[Live demo](LIVE_DEMO_URL) · [Docs](#docs)

## The problem

Paper-trading apps and backtests ignore brokerage, taxes and fees, so beginners learn strategies that lose money in reality. Happy Quanting puts the costs first: the charges are on the screen before you trade, and in every backtest result before the return.

## What it does

- **Every charge shown before you trade.** An order preview lists brokerage, taxes, exchange fees, depository and currency conversion line by line, on 35 markets and 13 brokers, from the same calculation that later charges the fill.
- **A virtual sim that replays real days.** Past days run through the live engine with no look-ahead, at up to 200 bars a second, with your orders, stops and algorithms.
- **A backtester with charges up front.** Total charges and their share of gross profit come before any return figure, next to a buy-and-hold comparison charged the same way.
- **A no-code block editor and a code editor.** Build a strategy on a canvas or in Monaco; both compile to the same checked source.
- **Deploy your algorithms on paper.** Run a tuned or saved algorithm live on its own sub-account, with pause, stop and a live log.
- **A marketplace where code never leaves the server.** Creators sell algorithms; performance is measured by the server, and the creator's fee is charged only on new profit highs.
- **Gym badges for disciplined trading.** Four regions, the Elite Four and a Champion badge.
- **Glossary tooltips** that explain every term where it appears.
- **Dark and light themes.**

## Try it in 30 seconds

1. Open the [live demo](LIVE_DEMO_URL) and sign up.
2. Go to Trade, search `RELIANCE.NS` and buy 10 shares. Watch the charge lines in the preview.
3. Open HFT, then Market, and subscribe to a creator's algorithm.

## How it's built

**Stack:** FastAPI, SQLite with SQLAlchemy and Alembic, Next.js 16, React 19, Tailwind 4, lightweight-charts, Monaco, React Flow, Playwright.

```
Browser -> Next.js (/api proxy) -> FastAPI -> trading engine -> SQLite
                                           -> market data: Yahoo | offline fake | replay
                                           -> background loops: orders, sims, backtests, subscriptions, deployments
```

**Tests:** 803 backend tests (offline, about 40 seconds) and 63 browser tests in 14 files covering every page.

- **Sandbox.** Uploaded code is checked against an allow-list on its syntax tree, then runs in a separate child process with time and memory limits; the engine stays in the parent.
- **IP protection.** Public marketplace views never carry code or settings, and a test scans every response for anything that would give them away.
- **Preview equals reality.** One function plans each order, and it serves the preview, the funds check and the fill.

## Honest limits

- No bid/ask spread and no slippage: fills use a single price, so results are optimistic by that much.
- Prices are delayed (about 15 minutes) and come from an unofficial feed, so stops and targets fire late.
- The sandbox is not safe for public upload; a hosted deployment turns it off (`HOSTED_MODE`).
- Borrow cost is a flat rate, not per stock; no leverage on buys, no T+1 settlement.
- Pokémon artwork, names and the tagline are a parody made for a hackathon.

The full list is in [docs/TRADING-RULES.md](docs/TRADING-RULES.md).

## Run locally

Needs Node.js and npm, and Python 3 on Windows through the `py -3` launcher.

```
npm run setup    # installs both sides, creates backend\.venv
npm run dev      # API on 8000 and web on 3000 (read the printed address)
npm run -s test:q  # backend tests, failures and a summary line only
npm run -s e2e   # browser tests on a private stack
```

On first start the server prints a one-time `Demo login: demo / <password>` line, or sign up at `/signup`. Set `MARKET_DATA_PROVIDER=fake` in `backend/.env` for deterministic offline prices.

## Docs

- [Features](docs/FEATURES.md): every page and what it does
- [Trading rules](docs/TRADING-RULES.md): the rules, what is not modelled, known gaps
- [Charges](docs/CHARGES.md): where the figures come from and which are unverified
- [API](docs/API.md): all 89 routes
- [Architecture](docs/ARCHITECTURE.md): a map of the code
- [Deploying](docs/DEPLOY.md): Hugging Face Space and Vercel
- [Algorithm rules](docs/algo-rules.md): what uploaded and editor code may do
- [Roadmap](docs/ROADMAP.md)

**Paper trading only, not financial advice.** No real money is involved.
