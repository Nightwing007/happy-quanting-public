# Architecture

Map of the code. Start here, open only what a step touches, and fix this file in the same
step if it turns out to be wrong.

## Shape

```
Browser → Next.js (frontend/, proxies /api/* via next.config.ts BACKEND_URL)
        → FastAPI (backend/app/main.py) → engine (app/trading/) → SQLite (backend/data/app.db)
                                        → market data (app/market_data/) → Yahoo (yfinance) | fake | replay
```

## Backend — `backend/app/`

| Area | Entry points | Owns |
|---|---|---|
| App wiring | `main.py` | routers, exception handlers (`{"detail","code"}`), lifespan: migrate → demo/first-run → currency convert → background loops (live tick, sim driver, backtest worker) |
| Config / DB | `config.py`, `db.py`, `migrate.py` | settings from `backend/.env`; `DecimalString`, `UTCDateTime`; migrate on startup |
| Models / schemas | `models.py`, `schemas.py` (large — grep) | all tables; all API models (`Money` = Decimal as fixed-point string) |
| Market data | `market_data/base.py` (protocol, `Quote`, `Bar`, `ALLOWED_RANGES`), `yahoo.py` (only yfinance import), `fake.py`, `cache.py`, `fx.py`, `__init__.py` (`get_provider`, `get_quotes`) | prices, search, fundamentals, minor-unit normalising (GBp→GBP) |
| Historical data | `market_data/history.py` (`get_history`, `validate_range`, `bar_cache`/`history_spans`), `market_data/replay.py` (`ReplayProvider`, `bar_span`) | cached past bars; replay with no look-ahead |
| Engine context | `trading/context.py` (`TradingContext(db, account, provider, now)`), `trading/tick.py` (`run_tick`) | every engine call is scoped to one account and one clock |
| Paper trading engine | `trading/engine.py` (≈1,900 lines — grep for `def `) | `_plan` → legs, `plan_cost`, `place_order`, `_fill`, `exit_trade`, `get_portfolio`, `get_payouts`, previews, `account_for_user`, `live_context(db, provider, user_id)` |
| Trading costs | `trading/fees.py` (`Fee`, `Charge`, `calculate_charges`, `break_even_price`), `trading/markets.py` (35 `Market`s, `ShortRule`, `market_for`), `trading/brokers.py` (13 `Broker`s) | charges as data tables with `source`/`checked` |
| Market hours | `trading/hours.py` (`market_status`, `can_fill`, `session_bounds`, `timezone_of`) | exchange_calendars, AMO waiting, labels in exchange tz |
| Shorts / stop-loss / square-off | in `engine.py`: `accrue_financing`, `square_off_due`, `set_protection`, `trigger_protected_trades` | per-market short rules; OCO protection |
| Errors / money | `trading/errors.py` (each `TradingError` has `code`), `trading/money.py` (`money`, `trim8`) | |
| Metrics | `metrics.py` | 5 company metrics + crypto 4, sector ranges |
| Indicators | `indicators.py` | pure `sma ema rsi atr bollinger highest lowest` |
| Virtual sim | `sim/runner.py` (`build_context`, `advance`, `create_session`), `sim/driver.py`, `sim/strategies.py` (`resolve`, `ensure`, `tick`, `drop`, `describe`, `log_lines`: one in-memory `StrategyRun` per session), `SimSession.strategy_kind/…` (migration 0015) | replay a past range through the real engine; a session may run a library, saved, source or marketplace-listing strategy (listing sims hide code, settings and logs) |
| Strategy framework | `algos/api.py` (`Strategy`, `Param`, `StrategyContext` facade, `validate_params`), `algos/hq.py` (public names), `algos/runner.py` (`run_strategy_on`, next-bar fills, sizing incl. charges), `algos/library/` (5 algos, `LIBRARY`) | the contract all algorithms follow |
| Code rules | `docs/algo-rules.md` (author's contract), `algos/rules.py` (limits incl. `MAX_WARMUP_BARS`, allowed imports, forbidden names; a test keeps the doc in step), `algos/validate.py` (`validate_source`, `extract_meta` incl. the `warmup_bars` literal, `dry_run(runner=)`, `validate_and_dry_run`), `POST /api/algos/validate` | uploaded code never runs before the AST check; in-process dry run is not a sandbox |
| Sandbox | `algos/sandbox.py` (`load_strategy(source)` -> `SandboxedStrategy`, `run_in_subprocess`, `Limits`, `SandboxError`), `run_backtest(source=)`, `POST /api/algos/validate` | one spawned child per run; the parent owns the engine and answers each `ctx` call; limits from `rules.py` |
| Backtester | `algos/backtest.py` (`run_backtest`, metrics), `algos/jobs.py` (queue + worker) | results JSON, buy-and-hold comparison |
| Block editor (backend) | `algos/blocks/catalog.py` (the block catalog as data: ports, settings, lookback, snippets), `algos/blocks/compile.py` (`validate_graph`, `compile_graph`, `validate_custom`), `algos/blocks/custom.py` (group and code definitions), `api/blocks.py` (`/api/blocks/catalog|compile|custom`), `models.CustomBlock`, `UserAlgo.graph` (migration 0017) | a graph of blocks compiles to a Strategy source file checked by `validate_source`; graphs and custom blocks are owner-only |
| Marketplace | `marketplace/listings.py` (`create_listing`, `update_listing`, `publish_listing`, `retire_listing`, `get_listing_for`, `MarketplaceError`), `marketplace/performance.py` (`compute_performance`, `performance_only`, worker hook `run_next_queued`), `api/marketplace.py` (`/api/marketplace/*`), `models.AlgoListing`/`ListingPerformance` | listings with server-measured 3mo/1y/3y performance (totals and curves only); public views never carry code, settings or trades, only `/mine` does |
| Subscriptions | `marketplace/subscriptions.py` (`subscribe`, `stop`, `advance_stop`, `settle_fees`, `earnings`), `marketplace/live.py` (`run_subscriptions_once`, in-memory run per subscription, `drop`), `api/marketplace.py` (`/subscribe`, `/subscriptions`, `/earnings`), `models.Subscription`/`FeeLedger`/`CashTransfer`; `StrategyRun(closed_only=, rebind())` | each subscription trades its own `kind="algo"` account funded from the live cash; the loop steps it after the live tick; creator fee = share of realized profit above a high-water mark, paid to the creator's live account |
| Listing versions | `models.ListingVersion`, `marketplace/listings.py` (`code_for`, `versions_of`, `_record_version`), `marketplace/subscriptions.py` (`upgrade`), `POST /api/marketplace/subscriptions/{id}/upgrade`, `BacktestIn.source` (`jobs._queue_source`, `Backtest.source`) | every version's code is kept server-side; a subscription is pinned to `listing_version` and `live._build` runs `code_for(listing, sub.listing_version)`; public views list version numbers and changelogs only |
| Marketplace seed | `marketplace/seed.py` (`seed_marketplace`), `backend/seed/algos/*.py` (five uploaded-code strategies), `scripts/seed_marketplace.py` (`--compute-now`) | five persona creators (`password_hash="!"`, PokeAPI avatar URL) each with one published listing; idempotent by username and listing name; run at startup when `seed_demo_marketplace` and `background_jobs` are on |
| Auth | `auth.py` (scrypt hash, hashed session tokens, `login_limiter`, demo password), `api/auth.py` (`/api/auth/signup|login|logout`, `/api/me`), `models.User`/`UserSession`; cookie `hq_session` | every route except health, `/api/market/*`, `/api/brokers`, `/api/algos/library` and signup/login/logout needs a user; sims, backtests, saved algos and accounts are filtered by owner (`test_scoping.py` walks the OpenAPI paths to prove it) |
| API routes | `api/deps.py` (`DbSession`, `Provider`, `CurrentUser`, `LiveContext`, `get_sim_context`, `SymbolParam`), `api/trading.py` (`build_router(prefix, context_dep)` — mounted for live and for sims), `api/market.py`, `api/sim.py`, `api/algos.py` (library + `/mine`, which also holds editor `source`), `api/backtests.py`, `api/settings.py`, `api/watchlist.py` | |

Migrations: `backend/migrations/versions/NNNN_name.py`, numbered with `--rev-id`; `migrations/env.py`
takes a connection from the caller. Latest number: see `backend/migrations/versions/`.

## Frontend — `frontend/src/`

| Area | Entry points |
|---|---|
| API client | `lib/api.ts` (one function per route, `ApiError` with `code`, optional `base` path), `lib/queries.ts` (TanStack hooks + keys; trading hooks read the base from `lib/trading-scope.tsx`), `lib/types.ts` (aliases), `lib/api-types.ts` (**generated**, 3,600 lines — grep, never read whole or edit) |
| Formatting | `lib/format.ts` (the only place money strings become numbers; `isZero`, `formatMoney`, Indian units), `lib/sim-format.ts` (`zoneShortName`), `lib/algo-format.ts`, `lib/order-words.ts`, `lib/charges.ts` |
| Charts | `components/trade/price-chart.tsx` (lightweight-charts v5; `markers`, `priceLines`, `incremental`), `lib/chart-markers.ts`, `lib/chart-protection.ts`, `components/algos/series-chart.tsx` |
| Trading UI | `components/trade/{order-ticket,chart-panel,quote-header,metrics-card}.tsx`, `components/{trades-table,orders-table,exit-dialog,protection-dialog,order-legs,payouts-panel,payout-card}.tsx` |
| Pages | `app/page.tsx` (dashboard, `components/dashboard/*`), `app/trade/`, `app/orders/`, `app/payouts/`, `app/settings/`, `app/login/`, `app/signup/`, `app/profile/`, `app/sim/` + `components/sim/*`, `app/algos/` + `components/algos/*`, `app/algos/blocks` + `components/blocks/*` (block editor: `@xyflow/react` canvas, `graph.ts` converts to the server graph, `templates.ts`, compile is `useCompileBlocks`; reuses editor save dialog, Preview, SimPanel, read-only Monaco), `app/algos/editor` + `components/editor/*` (Monaco editor, `lib/hq-api-hints.ts` autocomplete list, save to `/api/algos/mine` with `source`, test panels reuse `create/upload-flow`'s `Preview`; sim page shows `components/sim/strategy-panel.tsx`), `app/marketplace/{,[id],subscriptions,earnings}`, `app/creators/[username]` + `components/marketplace/*`, `app/create/{,upload}` + `components/create/*` (code box, rules panel from `GET /api/algos/rules`, upload flow; `?listing=` = new-version mode) (`lib/marketplace-format.ts`) |
| Shell | `app/layout.tsx`, `app/providers.tsx`, `components/site-header.tsx`, `components/backend-status-banner.tsx`, `components/data-notice.tsx` |
| UI kit | `components/ui/*` — shadcn base-nova on `@base-ui/react` (`render` prop, not `asChild`); don't read unless changing one |

## Where to look for X

| X | Look in |
|---|---|
| What an order costs | `fees.calculate_charges`, rates in `markets.py` / `brokers.py`, called only via `engine.plan_cost` |
| Why an order didn't fill | `hours.can_fill`, `engine.fill_open_orders`, quote `as_of` |
| How a sell splits into close + short | `engine._plan` (legs) |
| Rupee conversion / FX markup | `fees.calculate_charges` (fx line last), `market_data/fx.py`, `engine.convert_account_currency` |
| Indian square-off time | `ShortRule.square_off_minutes_before_close` in `markets.py`, `engine.square_off_due` |
| Stop / target firing | `engine.trigger_protected_trades` (stop checked first) |
| A route's response shape | `schemas.py` (grep the model name) |
| Account isolation | every query filters `ctx.account.id`; `tests/test_context.py` |
| Replay / no look-ahead | `market_data/replay.py`, `tests/test_history.py` |
| Daily-bar fills (next open) | `ReplayProvider` sessions + `hours.session_bounds`, `algos/runner.py` |
| Strategy API names | `algos/hq.py`, `algos/api.py` |
| Sample bars (shape of history data) | `docs/samples/bars-RELIANCE.NS-1m.json` |

## Tests — `backend/tests/`

`conftest.py` fixtures: offline fake provider (`fake_provider`), in-memory DB (`db`), `client`,
`fixed_clock`, `zero_costs`, autouse `markets_always_open` (opt out with `@pytest.mark.real_calendar`).
Group → files (used by `scripts/qtest.py`):

| Group | Files |
|---|---|
| engine | `test_engine test_costs_engine test_costs_api test_fees test_shorting test_protection test_payouts test_trading_api test_context` |
| market | `test_market_data test_market_api test_history test_market_hours test_metrics test_indicators` |
| sim | `test_sim test_sim_strategies` |
| algos | `test_algos test_backtest test_validate test_sandbox test_blocks` |
| auth | `test_auth test_scoping` |
| db | `test_migrations` |
| marketplace | `test_marketplace test_subscriptions test_seed test_listing_versions` |

Large test files (`test_backtest`, `test_shorting`, `test_sim`, `test_fees`): grep for the test name, read a range.
