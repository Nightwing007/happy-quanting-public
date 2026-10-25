# Trading rules

How the paper-trading engine behaves, what it deliberately leaves out, and the known gaps. The same rules apply to live trading, the virtual sim, backtests and deployed algorithms. Where charges come from is in [CHARGES.md](CHARGES.md); what the app offers is in [FEATURES.md](FEATURES.md).

## The rules

- **Money.** The account is in INR and starts with Rs 10,00,000. Every trade pays its real costs; there is no zero-cost mode. Instruments in other currencies are converted at the live exchange rate, with the broker's conversion markup where it has one.
- **Market hours and waiting orders.** An order placed while its market is closed is accepted and waits for the open, like an after-market order (AMO), and fills at the first fresh quote of the session. A waiting order does not reserve cash: it is checked when placed and again when it fills. Orders fill only against a quote from the current session, so an old closing price right after an open is never used. An Indian intraday short cannot wait (see below). Calendars are real: holidays, half days and lunch breaks. Crypto never closes.
- **Limit orders.** A limit order fills when the market reaches its price, and it fills at the market price at that moment, not at the limit. A limit order that rested before being hit is charged as a maker where the market has maker rates.
- **Per-lot trades.** Buying twice gives two trades. How you exit depends on the market, as in real life: **US and crypto** let you name the lot you are exiting (specific-lot identification); **India and every other market** pool holdings, so an exit takes the oldest lot first (FIFO) whichever trade you started it from, and the app says so. Holdings on the dashboard are computed from the open trades.
- **Selling reads the way a broker reads it.** One sell closes your open buys first, oldest first, and only the remainder becomes a short. Sell 8 holding 5 and you close 5 and short 3, charged as two separate contracts under different products.
- **Fractions** where the market allows them: US shares to 4 decimals, crypto to 8.
- **Shorting, per market.**
  - *India (NSE, BSE):* intraday only. 20% of the value is blocked as margin (the proceeds are not paid out), there is no borrow fee, and whatever is still open 10 minutes before the close is bought back for you ("Squared off by broker"). It is charged with the intraday tables (different STT and stamp duty, no depository charge) and cannot be placed while the market is closed.
  - *US:* may be held overnight. 50% margin (Reg T), roughly 3% a year borrow charged daily on the entry value, whole shares only.
  - *Crypto:* held as long as you like on 20% margin (5x), with funding of 0.01% every 8 hours (10.95% a year) charged on the entry value.
  - *Everywhere else:* shorting is not offered, as for most retail accounts.
- **Margin, not proceeds; cash never negative.** A short blocks margin out of your cash. Available cash is cash less margin used and can never go below zero; an order that would take it there is refused.
- **Stop-loss and target.** Attached to a trade, not an order type. Set one or both: whichever price is reached first closes the trade's whole open part and the other stops applying, like a broker's one-cancels-other GTT. It fills **at the market price**, not at the price you set, so a gap through your stop gets you out lower. If one price is crossed by a gap past both, the stop wins. It lapses after a year, like a GTT. It is only watched while the market is open, against a fresh quote. There is no trailing stop.
- **Preview equals reality.** The preview of an order, the funds check and the fill all use the same calculation, so the charges you see are the charges you pay.
- **No profit taxes, deliberately.** No capital-gains tax and no 1% crypto TDS. The project teaches transaction costs, which are paid whether you win or lose, and mixing in profit taxes would blur that. (Transaction taxes such as STT, stamp duty and the European financial transaction taxes are charged.)
- **A background loop** runs every 60 seconds while the server is up. It fills limit orders and orders that waited for the open, fires stop-losses and targets, squares off Indian intraday shorts, and charges borrow and funding. Nothing happens while the server is off, and it catches up on borrow and funding when it returns.

## What is deliberately not modelled

The honest part. If a cost or rule is not on the list above, assume it is missing.

- **No bid/ask spread.** Often the largest real cost on a retail trade. Orders fill at the quote's single price.
- **Delayed prices** (roughly 15 minutes from Yahoo), so there is no order-book simulation and stop-losses and targets fire late, against a price that is already old.
- **No market impact or slippage.** A large order fills at the same price as a small one.
- **A flat borrow rate** (3% a year in the US) instead of per-stock rates; hard-to-borrow shorts cost far more in reality.
- **No leverage on buys.** Buys need the full amount. Intraday margin on purchases is deliberately left out; it makes it too easy to blow up an account while learning.
- **No T+1 settlement** and **no circuit limits** (price bands that halt trading).
- **No capital-gains tax and no crypto TDS**, and no bank charges for sending money abroad under India's LRS.
- **Exchange calendars have limits.** Indian holidays are only known about a year ahead; past that the market status is "unknown" and trading is allowed rather than refused.
- **Simplifications in the charge tables:**
  - The depository (DP) charge is applied to every sell order; in reality it is once per share per day, so two sells of the same share in a day pay it twice here.
  - The French, Italian and Spanish financial transaction taxes are applied to every listed share, though they really apply only to companies above a market-value threshold.
  - UK stamp duty is applied to every UK share, though AIM and some foreign companies are exempt.
  - Local sales taxes on commissions (other than India's GST) are not modelled, nor are volume tiers (Mudrex's cheaper tiers, for example) or introductory offers.
- **The sector ranges for company metrics are hand-written rules of thumb**, not a live feed. Yahoo publishes no sector benchmarks, and the card says so.

## Known gaps

- **The sandbox is not a security boundary for a public site** (see [FEATURES.md](FEATURES.md#code-rules-and-sandbox)). Its limits are 2 CPU seconds per hook, 30 seconds and 256 MB per run, 50 KB of source, and a literal `warmup_bars` of at most 1000. The memory limit on Windows is a polled check, and the POSIX path is untested on this machine. A hosted deployment (`HOSTED_MODE=true`) refuses all uploaded and editor code instead; see [DEPLOY.md](DEPLOY.md).
- **Yahoo history is short for small bars,** and the sim and the backtester refuse earlier dates and say what the earliest is: about 30 days for 1-minute bars (fetched in 7-day pieces), about 60 days for 5-, 15- and 30-minute bars, about 730 days for hourly, and no limit for daily, weekly and monthly. This is why the marketplace's "intraday" demo strategies use hourly bars.
- **Pokémon artwork, names and the tagline are a parody made for a hackathon,** and Yahoo data is an unofficial, delayed feed for personal use. Both must be replaced before any commercial launch. Creator avatars are loaded at runtime from PokeAPI and never committed.
- **The trading-hours block uses a fixed UTC offset** that you type in minutes, because strategy code has no exchange time zone. It does not follow clock changes, and it needs intraday bars.
- **The block editor has no undo.** Delete a block and it is gone (you can reload a template or re-add it).
- **Block algorithms, deployments and the marketplace are paper trading as well.** They trade on delayed prices with the same charges and no spread or slippage, so published performance is optimistic by that much.
