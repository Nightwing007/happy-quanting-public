# API

Every route the app serves (89), generated from its OpenAPI schema (`backend/scripts/export_openapi.py`) and grouped by tag. The running backend also serves interactive docs at `/docs`.

- Symbols always travel in query parameters, never in the path, because Yahoo symbols contain `^`, `=` and `.`.
- All routes need a logged-in user (the `hq_session` cookie) except health, `/api/market/*`, `/api/brokers`, `/api/algos/library`, `/api/algos/rules`, the badge catalog and signup/login/logout.
- The sim routes mirror the live trading routes under `/api/sim/sessions/{session_id}`.
- Money is always a string with a fixed number of decimals.
- Trading errors come back as HTTP 400 with `{"detail": "<a sentence for people>", "code": "<stable_name>"}`. Match on `code`, never on the sentence. In hosted mode the routes that would take uploaded code answer 403 `disabled_in_hosted_mode`.
- Public views of marketplace listings never carry code, settings or trades; only `/api/marketplace/mine` does.

| Group | Routes |
| --- | --- |
| health | 1 |
| auth and profile | 5 |
| market data | 5 |
| live trading | 12 |
| settings and brokers | 3 |
| watchlist | 3 |
| virtual sim | 16 |
| algorithms | 8 |
| block editor | 7 |
| backtests | 4 |
| marketplace | 14 |
| deployments | 6 |
| badges | 5 |
| **Total** | **89** |

## Health (1)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server status, data source and account currency |

## Auth and profile (5)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/signup` | Create an account and log in |
| POST | `/api/auth/login` | Log in (sets the session cookie) |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/me` | The logged-in user |
| PUT | `/api/me` | Change display name, bio and avatar |

## Market data (5)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/market/search` | Search instruments by name or symbol (`q`) |
| GET | `/api/market/quote` | Latest price, day change and market status for a `symbol` |
| GET | `/api/market/metrics` | Company metrics against sector ranges (a coin's own figures for crypto) |
| GET | `/api/market/history-limits` | The earliest date available for each bar size |
| GET | `/api/market/bars` | Candles for a `symbol`, `interval` and `range`, with optional indicators |

## Live trading (12)

| Method | Path | Purpose |
| --- | --- | --- |
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
| POST | `/api/trades/{trade_id}/protection/preview` | Check a stop-loss and target and show what each would leave you with |
| PUT | `/api/trades/{trade_id}/protection` | Set or clear a trade's stop-loss and target |

## Settings and brokers (3)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/settings` | The chosen broker for each segment |
| PUT | `/api/settings` | Change the chosen brokers |
| GET | `/api/brokers` | Every broker by segment, with its notes, markets and sources |

## Watchlist (3)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/watchlist` | The watchlist with live prices |
| POST | `/api/watchlist` | Add a symbol |
| DELETE | `/api/watchlist` | Remove a symbol (`symbol`) |

## Virtual sim (16)

| Method | Path | Purpose |
| --- | --- | --- |
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
| POST | `/api/sim/sessions/{session_id}/trades/{trade_id}/protection/preview` | Preview protection in the session |
| PUT | `/api/sim/sessions/{session_id}/trades/{trade_id}/protection` | Set a stop-loss and target in the session |

## Algorithms (8)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/algos/library` | The five ready-made algorithms |
| GET | `/api/algos/rules` | The code rules and their numbers (public) |
| POST | `/api/algos/validate` | Check strategy code against the rules; nothing is saved |
| GET | `/api/algos/mine` | Your saved algorithms |
| POST | `/api/algos/mine` | Save an algorithm (library settings, code or a block graph) |
| GET | `/api/algos/mine/{algo_id}` | One saved algorithm (code and graph only for its owner) |
| PUT | `/api/algos/mine/{algo_id}` | Update a saved algorithm |
| DELETE | `/api/algos/mine/{algo_id}` | Delete a saved algorithm |

## Block editor (7)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/blocks/catalog` | Every block: ports, settings, help |
| POST | `/api/blocks/compile` | Check a block graph and compile it to strategy source |
| GET | `/api/blocks/custom` | Your custom blocks |
| POST | `/api/blocks/custom` | Make a custom block (group or code) |
| GET | `/api/blocks/custom/{block_id}` | One custom block |
| PUT | `/api/blocks/custom/{block_id}` | Update a custom block |
| DELETE | `/api/blocks/custom/{block_id}` | Delete a custom block |

## Backtests (4)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/backtests` | Your backtests |
| POST | `/api/backtests` | Queue a backtest (library, saved algorithm or source) |
| GET | `/api/backtests/{backtest_id}` | A backtest's status and results |
| DELETE | `/api/backtests/{backtest_id}` | Delete a backtest |

## Marketplace (14)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/marketplace/listings` | Published listings with measured performance (`?creator=` filter) |
| POST | `/api/marketplace/listings` | Create a draft listing |
| GET | `/api/marketplace/creators/{username}` | A creator's profile and listings |
| GET | `/api/marketplace/listings/{listing_id}` | One listing, public view |
| PUT | `/api/marketplace/listings/{listing_id}` | Edit a listing or add a version |
| GET | `/api/marketplace/mine` | Your own listings (the only view with code and settings) |
| POST | `/api/marketplace/listings/{listing_id}/publish` | Publish a listing |
| POST | `/api/marketplace/listings/{listing_id}/retire` | Retire a listing |
| POST | `/api/marketplace/listings/{listing_id}/refresh-performance` | Re-measure performance |
| POST | `/api/marketplace/listings/{listing_id}/subscribe` | Subscribe with capital from your live cash |
| GET | `/api/marketplace/subscriptions` | Your subscriptions |
| POST | `/api/marketplace/subscriptions/{subscription_id}/stop` | Stop a subscription and return the cash |
| POST | `/api/marketplace/subscriptions/{subscription_id}/upgrade` | Move to the listing's newer version |
| GET | `/api/marketplace/earnings` | Fees you have earned as a creator |

## Deployments (6)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/deployments` | Your deployments |
| POST | `/api/deployments` | Deploy one of your algorithms on a paper sub-account (library with settings, or saved) |
| GET | `/api/deployments/{deployment_id}` | One deployment: status, ledger, trades, orders and live log |
| POST | `/api/deployments/{deployment_id}/pause` | Pause (positions and stops stay) |
| POST | `/api/deployments/{deployment_id}/resume` | Resume a paused deployment |
| POST | `/api/deployments/{deployment_id}/stop` | Exit its positions through the engine and return the cash |

## Badges (5)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/badges/catalog` | Every badge, grouped by region |
| GET | `/api/badges/me` | Your earned badges and which are new |
| POST | `/api/badges/me/seen` | Mark badges as seen |
| POST | `/api/badges/me/summary-seen` | Dismiss the one-off backfill summary |
| GET | `/api/users/{username}/badges` | A user's earned badges (public) |
