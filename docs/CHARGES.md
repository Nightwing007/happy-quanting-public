# Charges

What every trade pays, where the figures live, and which ones could not be confirmed. For the rules that decide when charges apply (short selling, intraday products, waiting orders) see [TRADING-RULES.md](TRADING-RULES.md).

## Where the charges come from

Charges are data, not code. Every rate sits in a plain table with its source URL and the date it was checked, so it can be corrected without touching any logic:

- `backend/app/trading/markets.py` holds the taxes and exchange fees every trade on an exchange pays, whoever the broker is.
- `backend/app/trading/brokers.py` holds what each broker adds: brokerage, depository charges and currency-conversion markup.
- `backend/app/trading/fees.py` is the one calculator that applies them. Charges are rounded line by line to two decimals, as a contract note is.

The same calculation serves the order preview, the funds check and the fill, so the preview is exactly what you pay. Backtests and deployed algorithms charge every fill the same way.

Every charge line is itemised and explained on hover in the order ticket, the dashboard breakdown, the orders page and the payouts page (each closed trade shows the charges at both ends).

## Markets (35)

NSE, BSE, US, London, Dublin, Paris, Milan, Madrid, Hong Kong, Singapore, Seoul (KOSPI and KOSDAQ), Taiwan (TWSE and OTC), Shanghai, Shenzhen, Johannesburg, crypto, Germany (Xetra), Frankfurt, Tokyo, Toronto (and Toronto Venture), Australia, Amsterdam, Switzerland, Brussels, Vienna, Lisbon, Stockholm, Oslo, Copenhagen, Helsinki, New Zealand and Mexico. A symbol on any other exchange is refused rather than priced as American. All rates were last checked on 2026-10-24.

## Brokers (13)

| Segment | Brokers |
| --- | --- |
| Indian stocks | Zerodha, Groww (default), Upstox, Angel One, Dhan |
| International stocks | Interactive Brokers (default), INDmoney, Vested |
| Crypto | CoinDCX (default), CoinSwitch, WazirX, Mudrex, Binance |

You pick a broker for each segment in Settings; the choice changes the charges and which markets you can trade.

## Currency

Instruments in other currencies are converted at the live exchange rate, with the broker's conversion markup where it has one. The conversion line is always last on the charge list.

## Some figures could not be confirmed, and the code says so

`grep -rn UNVERIFIED backend/app` finds 23 marks: 7 in `markets.py`, 3 in `brokers.py` and 13 in `metrics.py`. By category:

- *Market taxes and fees (7; two are the module's own docstring and a section comment):* Singapore's clearing-fee cap (the current SGX page could not be read), whether South Africa's securities transfer tax applies to ETF units, Belgium's stock-exchange tax for clients of foreign brokers, and the markets where no transaction tax was found and none is charged (Germany, Japan, Canada, Australia, the Netherlands and others), since no authority publishes a list of taxes it lacks.
- *Broker fees (3; one of them is the module's own docstring):* Dhan's two quoted intraday rules and INDmoney's GST rate.
- *Company-metric ranges (13):* the dividend-yield bands for every sector (the other four metrics are sourced to Damodaran's NYU Stern datasets of January 2026).

Some figures were checked on 2026-09-15 and have **not been re-verified** since; they are marked as such in the code: INDmoney's currency-conversion markup (0.7%), Vested's (1%), CoinSwitch's fees (0.1% taker, 0% maker, + 18% GST), WazirX's fees (0.2% + 18% GST; its Rs 99 a month no-fee plan is not modelled), and the roughly 1% cost of converting rupees to USDT that CoinDCX, CoinSwitch, WazirX and Mudrex add when you buy a coin priced in dollars from a rupee account. Binance gets no such cost: there is no sourced figure for how an Indian user funds it.

Unconfirmed figures are marked `UNVERIFIED` rather than guessed.

## What is not charged

No capital-gains tax and no crypto TDS (a deliberate choice), no spread, no slippage, and a few simplifications in the tables. The full list is in [TRADING-RULES.md](TRADING-RULES.md#what-is-deliberately-not-modelled).
