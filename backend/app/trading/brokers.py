"""Brokers: what each charges on top of the market's own taxes and exchange fees.

Same rules as `markets.py`: every rate has a source and the date checked, and a figure that
could not be confirmed is marked `UNVERIFIED` (or its list left empty) rather than guessed.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .fees import Fee

D = Decimal
_CHECKED = "2026-10-24"
_OLDER_CHECK = "2026-09-15"  # figures checked on this date and not re-verified since
_EQ_ETF = frozenset({"equity", "etf"})

SEGMENTS = ("india", "international", "crypto")
SEGMENT_LABELS = {
    "india": "Indian stocks",
    "international": "International stocks",
    "crypto": "Crypto",
}
DEFAULT_BROKERS = {"india": "groww", "international": "ibkr", "crypto": "coindcx"}


@dataclass(frozen=True)
class Broker:
    code: str
    name: str
    segment: str
    fees: list[Fee] = field(default_factory=list)
    # The fees for an intraday trade, where they differ from `fees` (Indian brokers: a
    # different brokerage rule and no depository charge). None: same as `fees`.
    intraday_fees: list[Fee] | None = None
    fx_markup_percent: Decimal = D(0)  # worse-than-market rate when converting currency
    markets: tuple[str, ...] = ()  # market codes offered
    notes: str = ""
    source: str = ""
    checked: str = ""

    def offers(self, market_code: str) -> bool:
        return market_code in self.markets


# --- shared fee shapes ---------------------------------------------------------------------


def _indian_brokerage(percent: str, minimum: str, maximum: str, source: str) -> Fee:
    return Fee(
        "Brokerage",
        "brokerage",
        f"What the broker charges to place the order: {percent}% of the value, never less than "
        f"Rs {minimum} and never more than Rs {maximum}.",
        percent=D(percent),
        minimum=D(minimum),
        maximum=D(maximum),
        only_types=_EQ_ETF,
        source=source,
        checked=_CHECKED,
    )


def _dp_charge(amount: str, source: str, note: str = "") -> Fee:
    # Charged per scrip per sell day in reality. This model charges it on every sell order,
    # so two sells of the same share on one day pay it twice (a small overcharge).
    return Fee(
        "Depository (DP) charge",
        "depository",
        "A flat fee each time shares leave your demat account on a sale: the depository's Rs 3.5 "
        "plus the broker's own fee. It does not depend on how many shares you sell.",
        flat=D(amount),
        side="sell",
        only_types=_EQ_ETF,
        source=source + note,
        checked=_CHECKED,
    )


def _intraday_brokerage(percent: str, minimum: str | None, maximum: str, source: str) -> Fee:
    floor = f", never less than Rs {minimum}" if minimum else ""
    return Fee(
        "Brokerage",
        "brokerage",
        f"What the broker charges to place the order: {percent}% of the value{floor} and never "
        f"more than Rs {maximum}. Intraday trades pay no depository charge.",
        percent=D(percent),
        minimum=D(minimum) if minimum else None,
        maximum=D(maximum),
        only_types=_EQ_ETF,
        source=source,
        checked=_CHECKED,
    )


def _percent_brokerage(percent: str, maximum: str | None, source: str) -> Fee:
    cap = f", capped at ${maximum}" if maximum else ""
    return Fee(
        "Brokerage",
        "brokerage",
        f"What the broker charges to place the order: {percent}% of the value{cap}.",
        percent=D(percent),
        maximum=D(maximum) if maximum else None,
        only_types=_EQ_ETF,
        source=source,
        checked=_CHECKED,
    )


def _crypto_fee(percent: str, source: str, checked: str = _CHECKED) -> Fee:
    return Fee(
        "Trading fee",
        "brokerage",
        f"The exchange's fee on every trade: {percent}% of the value, the same whether you add "
        "or take liquidity.",
        percent=D(percent),
        maker_percent=D(percent),
        source=source,
        checked=checked,
    )


def _crypto_gst(source: str, checked: str = _CHECKED) -> Fee:
    return Fee(
        "GST",
        "gst",
        "18% goods and services tax on the exchange's trading fee. No tax is deducted from profit here.",
        percent=D("18"),
        on_categories=frozenset({"brokerage"}),
        source=source,
        checked=checked,
    )


def _ibkr(
    name: str,
    markets: tuple[str, ...],
    *,
    percent: str = "0",
    per_share: str = "0",
    minimum: str,
    max_percent: str | None = None,
    row: str,
) -> Fee:
    return Fee(
        f"Brokerage ({name})",
        "brokerage",
        "What Interactive Brokers charges to place the order, with a minimum per order"
        + (" and a cap as a share of the trade value." if max_percent else "."),
        percent=D(percent),
        per_share=D(per_share),
        minimum=D(minimum),
        max_percent=D(max_percent) if max_percent else None,
        only_types=_EQ_ETF,
        only_markets=frozenset(markets),
        source=f"https://www.interactivebrokers.com/en/pricing/commissions-stocks.php ({row}, "
        "IBKR Pro Fixed, IB SmartRouting)",
        checked=_CHECKED,
    )


# Buying a coin priced in USD from a rupee account on an Indian exchange means first converting
# rupees to USD/USDT, which costs about this much. It reaches the cost calculator as
# `fx_markup_percent`, so it is charged only when the coin's currency differs from the account's
# (BTC-USD in a rupee account; a coin priced in INR would not pay it).
# Checked 2026-09-15; not re-verified.
_CRYPTO_INR_CONVERSION = D("1")

_ZERODHA = "https://zerodha.com/charges/"
_GROWW = "https://groww.in/pricing"
_UPSTOX = "https://upstox.com/brokerage-charges/"
_ANGEL = "https://www.angelone.in/exchange-transaction-charges"
_DHAN = "https://dhan.co/pricing/"

# Markets where IBKR's per-market commission was read off its published schedule.
_IBKR_PRICED = (
    "US", "LSE", "XETRA", "FRA", "PAR", "MIL", "MAD", "AMS", "BRU", "VIE", "SIX", "STO", "OSL",
    "CPH", "LIS", "HKEX", "TSE", "TSX", "TSXV", "ASX", "SGX", "BMV",
)  # fmt: skip
# Markets IBKR serves but whose commission was not on the page consulted. Trades there pay the
# market's taxes but no brokerage until the schedule is recorded.
_IBKR_UNPRICED = ("IRE", "HEL", "KOSPI", "KOSDAQ", "TWSE", "TPEX", "SSE", "SZSE", "JSE", "NZX")

_ALL_BROKERS = [
    # --- Indian equity -------------------------------------------------------------------
    Broker(
        "zerodha",
        "Zerodha",
        "india",
        [_dp_charge("13", f"{_ZERODHA} (Rs 3.5 CDSL + Rs 9.5 Zerodha per scrip per sell, + GST)")],
        # Intraday: "0.03% or Rs 20 per executed order, whichever is lower", no depository charge.
        [
            _intraday_brokerage(
                "0.03", None, "20", f"{_ZERODHA} (equity intraday: 0.03% or Rs 20, whichever is lower)"
            )
        ],
        markets=("NSE", "BSE"),
        notes="Free equity delivery (no brokerage). Pays a flat Rs 13 + GST depository charge on every sale.",
        source=_ZERODHA,
        checked=_CHECKED,
    ),
    Broker(
        "groww",
        "Groww",
        "india",
        [
            _indian_brokerage("0.1", "5", "20", f"{_GROWW} (0.1% per order, max Rs 20, min Rs 5)"),
            _dp_charge("20", f"{_GROWW} (depository Rs 3.5 + Groww Rs 16.5 per sell, + GST)"),
        ],
        # Intraday brokerage is the same rule as delivery on Groww's pricing page; no DP charge.
        [
            _intraday_brokerage(
                "0.1", "5", "20", f"{_GROWW} (Rs 20 or 0.1% per executed order, whichever is lower, min Rs 5)"
            )
        ],
        markets=("NSE", "BSE"),
        notes="0.1% brokerage (min Rs 5, max Rs 20). Pays a flat Rs 20 + GST depository charge on a sale.",
        source=_GROWW,
        checked=_CHECKED,
    ),
    Broker(
        "upstox",
        "Upstox",
        "india",
        [
            Fee(
                "Brokerage",
                "brokerage",
                "What the broker charges to place the order: a flat Rs 20 per order.",
                flat=D("20"),
                only_types=_EQ_ETF,
                # UNVERIFIED: Upstox is believed to charge "Rs 20 or 2.5%, whichever is lower";
                # only the flat Rs 20 was confirmed, so very small orders are overcharged.
                source=f"{_UPSTOX} (Rs 20 per executed order)",
                checked=_CHECKED,
            ),
            _dp_charge("20", f"{_UPSTOX} (CDSL Rs 3.5 + Upstox Rs 16.5, + GST)"),
        ],
        # UNVERIFIED: whether Upstox applies a minimum to intraday brokerage; the page says only
        # "Rs 20 per executed order or 0.1% (whichever is lower)", so none is modelled.
        [
            _intraday_brokerage(
                "0.1", None, "20", f"{_UPSTOX} (Rs 20 or 0.1% per executed order, whichever is lower)"
            )
        ],
        markets=("NSE", "BSE"),
        notes="Flat Rs 20 brokerage per order (a lower cap for tiny orders is not modelled).",
        source=_UPSTOX,
        checked=_CHECKED,
    ),
    Broker(
        "angelone",
        "Angel One",
        "india",
        [
            _indian_brokerage("0.1", "5", "20", f"{_ANGEL} (lower of Rs 20 or 0.1%, min Rs 5)"),
            _dp_charge("20", f"{_ANGEL} (CDSL Rs 3.5 + Angel One Rs 16.5, + GST)"),
        ],
        # The page gives one brokerage rule for equity; the first-30-days free offer is not modelled.
        [_intraday_brokerage("0.1", "5", "20", f"{_ANGEL} (lower of Rs 20 or 0.1%, min Rs 5)")],
        markets=("NSE", "BSE"),
        notes="0.1% brokerage (min Rs 5, max Rs 20). Its NSE charge is 0.0030699%, which this "
        "model rounds to the standard 0.00307%.",
        source=_ANGEL,
        checked=_CHECKED,
    ),
    Broker(
        "dhan",
        "Dhan",
        "india",
        [_dp_charge("12.5", f"{_DHAN} (Rs 12.50 per instruction per ISIN, + GST)")],
        # UNVERIFIED: Dhan's page says both "Rs 20 or 0.03% per executed order, whichever is lower"
        # and, in its summary, "flat Rs 20 for intraday". The lower-of rule is modelled.
        [
            _intraday_brokerage(
                "0.03", None, "20", f"{_DHAN} (Rs 20 or 0.03% per executed order, whichever is lower)"
            )
        ],
        markets=("NSE", "BSE"),
        notes="Zero brokerage on delivery. Pays a flat Rs 12.50 + GST depository charge on every sale.",
        source=_DHAN,
        checked=_CHECKED,
    ),
    # --- International ------------------------------------------------------------------
    Broker(
        "ibkr",
        "Interactive Brokers",
        "international",
        [
            _ibkr("US", ("US",), per_share="0.005", minimum="1", max_percent="1", row="US Fixed"),
            Fee(
                "FINRA CAT fee",
                "regulatory",
                "A tiny regulatory fee Interactive Brokers passes on, per share traded.",
                per_share=D("0.000003"),
                only_types=_EQ_ETF,
                only_markets=frozenset({"US"}),
                source="https://www.interactivebrokers.com/en/pricing/commissions-stocks.php "
                "(FINRA Consolidated Audit Trail fees USD 0.000003 x quantity)",
                checked=_CHECKED,
            ),
            _ibkr("UK", ("LSE",), percent="0.05", minimum="3", row="UK, GBP"),
            _ibkr(
                "Europe",
                ("XETRA", "FRA", "PAR", "MIL", "MAD", "AMS", "BRU", "VIE"),
                percent="0.05",
                minimum="3",
                row="Germany/France/Italy/Spain/Netherlands/Belgium/Austria, EUR",
            ),
            _ibkr("Switzerland", ("SIX",), percent="0.05", minimum="5", row="Switzerland, CHF"),
            _ibkr("Sweden", ("STO",), percent="0.05", minimum="49", row="Sweden, SEK"),
            _ibkr("Norway", ("OSL",), percent="0.05", minimum="49", row="Norway, NOK"),
            _ibkr("Denmark", ("CPH",), percent="0.05", minimum="49", row="Denmark, DKK"),
            _ibkr("Portugal", ("LIS",), percent="0.15", minimum="6", row="Portugal, EUR"),
            _ibkr("Hong Kong", ("HKEX",), percent="0.08", minimum="18", row="Hong Kong, HKD"),
            _ibkr("Japan", ("TSE",), percent="0.08", minimum="80", row="Japan, JPY"),
            _ibkr(
                "Canada",
                ("TSX", "TSXV"),
                per_share="0.01",
                minimum="1",
                max_percent="0.5",
                row="Canada, CAD",
            ),
            _ibkr("Australia", ("ASX",), percent="0.08", minimum="6", row="Australia, AUD"),
            _ibkr("Singapore", ("SGX",), percent="0.08", minimum="2.5", row="Singapore, SGD"),
            _ibkr("Mexico", ("BMV",), percent="0.1", minimum="60", row="Mexico, MXN"),
        ],
        fx_markup_percent=D("0.03"),
        markets=_IBKR_PRICED + _IBKR_UNPRICED,
        notes="Per-share or percentage commissions with a minimum per order, by market (IBKR Pro "
        "Fixed). Converts currency at the market rate plus 0.03%. No commission is recorded yet "
        "for Ireland, Finland, Korea, Taiwan, Shanghai, Shenzhen, Johannesburg or New Zealand, "
        "so trades there pay only the market's taxes.",
        source="https://www.interactivebrokers.com/en/pricing/commissions-stocks.php and "
        "https://www.interactivebrokers.com/en/pricing/commissions-spot-currencies.php "
        "(auto-conversion adds or subtracts 0.03%)",
        checked=_CHECKED,
    ),
    Broker(
        "indmoney",
        "INDmoney",
        "international",
        [
            Fee(
                "Brokerage",
                "brokerage",
                "What the broker charges to place the order: 0.25% of the value, capped at $25.",
                percent=D("0.25"),
                maximum=D("25"),
                only_types=_EQ_ETF,
                source="https://www.indmoney.com/us-stocks (0.25% per trade, max $25, excl GST)",
                checked=_CHECKED,
            ),
            Fee(
                "GST",
                "gst",
                "18% goods and services tax on the brokerage.",
                percent=D("18"),
                on_categories=frozenset({"brokerage"}),
                # UNVERIFIED: INDmoney says "excl GST" without naming the rate; 18% is India's
                # rate and what Zerodha's page lists for its US equity brokerage.
                source="https://www.indmoney.com/us-stocks (brokerage excl GST); rate from "
                "https://zerodha.com/charges/ (US equity, 18% on brokerage)",
                checked=_CHECKED,
            ),
        ],
        # Checked 2026-09-15; not re-verified.
        # https://www.indmoney.com/us-stocks: "about 0.7%, roughly 60 paise per dollar".
        fx_markup_percent=D("0.7"),
        markets=("US",),
        notes="US stocks only: 0.25% brokerage (max $25) + GST, and about 0.7% currency-conversion "
        "markup (from an earlier check, not re-verified).",
        source="https://www.indmoney.com/us-stocks",
        checked=_CHECKED,
    ),
    Broker(
        "vested",
        "Vested",
        "international",
        [
            _percent_brokerage(
                "0.25",
                "35",
                "https://vestedfinance.com/in/pricing/ (Basic plan: 0.25% of trade amount, max $35; "
                "Premium plan 0.15%)",
            )
        ],
        # Checked 2026-09-15; not re-verified.
        # https://vestedfinance.com/pricing: "the partner bank's markup ... about 1%".
        fx_markup_percent=D("1"),
        markets=("US",),
        notes="US stocks only, Basic plan: 0.25% brokerage (max $35), and about 1% currency-conversion "
        "markup from its partner bank (from an earlier check, not re-verified).",
        source="https://vestedfinance.com/in/pricing/",
        checked=_CHECKED,
    ),
    # --- Crypto -------------------------------------------------------------------------
    Broker(
        "coindcx",
        "CoinDCX",
        "crypto",
        [
            # The page lists INR-market spot at 0.50% and crypto-to-crypto (USDT) spot at 0.17%,
            # Regular tier, maker and taker alike. Yahoo prices crypto in USD, closest to the
            # USDT market, so 0.17% is used.
            _crypto_fee("0.17", "https://coindcx.com/fees (Spot C2C, Regular 1, maker & taker 0.17%)"),
            _crypto_gst("https://coindcx.com/fees (18% GST on fees)"),
        ],
        fx_markup_percent=_CRYPTO_INR_CONVERSION,
        markets=("CRYPTO",),
        notes="0.17% on USDT markets (0.50% on INR markets) + 18% GST. A coin priced in dollars "
        "also pays about 1% to convert rupees to USDT. No TDS is modelled.",
        source="https://coindcx.com/fees",
        checked=_CHECKED,
    ),
    Broker(
        "coinswitch",
        "CoinSwitch",
        "crypto",
        [
            # Checked 2026-09-15; not re-verified.
            # https://coinswitch.co/: 0.1% taker, 0% maker. The only broker where they differ.
            Fee(
                "Trading fee",
                "brokerage",
                "The exchange's fee on every trade: 0.1% of the value when you take liquidity "
                "(a market order), nothing when your limit order rests and adds it.",
                percent=D("0.1"),
                maker_percent=D("0"),
                source="https://coinswitch.co/ (0.1% taker, 0% maker; checked 2026-09-15, not re-verified)",
                checked=_OLDER_CHECK,
            ),
            _crypto_gst(
                "https://coinswitch.co/ (18% GST on the fee; checked 2026-09-15, not re-verified)",
                _OLDER_CHECK,
            ),
        ],
        fx_markup_percent=_CRYPTO_INR_CONVERSION,
        markets=("CRYPTO",),
        notes="0.1% taker (market orders), 0% maker (resting limit orders) + 18% GST, from an "
        "earlier check, not re-verified. A coin priced in dollars also pays about 1% to convert "
        "rupees to USDT.",
        source="https://coinswitch.co/",
        checked=_CHECKED,
    ),
    Broker(
        "wazirx",
        "WazirX",
        "crypto",
        [
            # Checked 2026-09-15; not re-verified.
            # https://wazirx.com/: 0.2%, maker and taker alike.
            _crypto_fee(
                "0.2",
                "https://wazirx.com/ (0.2% maker & taker; checked 2026-09-15, not re-verified)",
                _OLDER_CHECK,
            ),
            _crypto_gst(
                "https://wazirx.com/ (18% GST on the fee; checked 2026-09-15, not re-verified)", _OLDER_CHECK
            ),
        ],
        fx_markup_percent=_CRYPTO_INR_CONVERSION,
        markets=("CRYPTO",),
        notes="0.2% maker and taker + 18% GST, from an earlier check, not re-verified. A Rs 99 a "
        "month plan removes the trading fee; it is not modelled. A coin priced in dollars also "
        "pays about 1% to convert rupees to USDT.",
        source="https://wazirx.com/",
        checked=_CHECKED,
    ),
    Broker(
        "mudrex",
        "Mudrex",
        "crypto",
        [
            _crypto_fee("0.45", "https://mudrex.com/fee (spot, INR-native, under Rs 2 lakh: 0.45%)"),
            _crypto_gst("https://mudrex.com/fee (18% GST on trading fees, buy and sell)"),
        ],
        fx_markup_percent=_CRYPTO_INR_CONVERSION,
        markets=("CRYPTO",),
        notes="0.45% at the lowest volume tier + 18% GST. Lower tiers for heavy traders are not "
        "modelled. A coin priced in dollars also pays about 1% to convert rupees to USDT. No TDS "
        "is modelled.",
        source="https://mudrex.com/fee",
        checked=_CHECKED,
    ),
    Broker(
        "binance",
        "Binance",
        "crypto",
        [
            _crypto_fee("0.1", "https://www.binance.com/en/fee/trading (Regular user, maker/taker 0.100%)"),
        ],
        markets=("CRYPTO",),
        # No rupee-to-USDT markup: there is no sourced figure for how an Indian user funds Binance
        # (P2P premiums vary), so none is invented here.
        notes="0.1% maker and taker at the regular tier. A global exchange: no Indian GST is added, "
        "and no rupee conversion cost is modelled (how an Indian user funds it varies).",
        source="https://www.binance.com/en/fee/trading",
        checked=_CHECKED,
    ),
]

BROKERS: dict[str, Broker] = {b.code: b for b in _ALL_BROKERS}


def brokers_for_segment(segment: str) -> list[Broker]:
    return [b for b in _ALL_BROKERS if b.segment == segment]


def get_broker(code: str) -> Broker:
    """The broker with this code. Raises KeyError for an unknown code."""
    return BROKERS[code]
