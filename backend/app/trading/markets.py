"""Markets: the taxes and exchange fees every trade on an exchange pays, whoever the broker is.

Each rate carries `source` and `checked`. Where a figure could not be confirmed it says
`UNVERIFIED` and why, or the list is left empty rather than filled with a guess. Broker
commissions live in `brokers.py`.

Known gaps shared by every market below:
- Local sales taxes on a broker's commission (other than India's GST) are not modelled.
- Fees that depend on the specific company or share class (BSE scrip groups, UK AIM shares,
  company size for the European transaction taxes) cannot be known from a Yahoo symbol; each
  entry says how it simplifies.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal

from .errors import UnsupportedMarket
from .fees import Fee

D = Decimal
_CHECKED = "2026-10-24"

# --- India ---------------------------------------------------------------------------------

_ZERODHA_CHARGES = "https://zerodha.com/charges/"
_GROWW_PRICING = "https://groww.in/pricing"
_EQ = frozenset({"equity"})
_EQ_ETF = frozenset({"equity", "etf"})

_INDIA_STT = Fee(
    "Securities transaction tax (STT)",
    "tax",
    "A tax the government charges on every delivery trade, on the buy and again on the sell: "
    "0.1% of the value. You pay it whether you win or lose.",
    percent=D("0.1"),
    only_types=_EQ,
    # ETFs are charged no STT in this model, a simplification: Zerodha's support page says other
    # ETFs pay 0.001% on the sell side (delivery) while gold, liquid and gilt ETFs pay none, and the
    # kind of ETF is not known from its symbol.
    # source: https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/stt-etfs,
    # checked 2026-10-24
    source=f"{_ZERODHA_CHARGES} and {_GROWW_PRICING} (equity delivery, 0.1% buy and sell)",
    checked=_CHECKED,
)
_INDIA_STAMP = Fee(
    "Stamp duty",
    "tax",
    "A state tax on buying shares: 0.015% of the value. Only the buyer pays it.",
    percent=D("0.015"),
    side="buy",
    only_types=_EQ_ETF,
    source=f"{_ZERODHA_CHARGES} and {_GROWW_PRICING} (delivery, 0.015% on buy side)",
    checked=_CHECKED,
)
_INDIA_SEBI = Fee(
    "SEBI turnover fee",
    "regulatory",
    "The market regulator's fee: Rs 10 per crore traded (0.0001%).",
    percent=D("0.0001"),
    only_types=_EQ_ETF,
    source=f"{_ZERODHA_CHARGES} (Rs 10 / crore), {_GROWW_PRICING} (0.0001%)",
    checked=_CHECKED,
)
_INDIA_GST = Fee(
    "GST",
    "gst",
    "18% goods and services tax on the services you are billed for: brokerage, exchange fee, "
    "SEBI fee and depository charge. Not charged on STT or stamp duty, which are taxes, not services.",
    percent=D("18"),
    on_categories=frozenset({"brokerage", "exchange", "regulatory", "depository"}),
    source=f"{_ZERODHA_CHARGES} (18% on brokerage + SEBI + transaction charges), "
    f"{_GROWW_PRICING} (also on DP charges)",
    checked=_CHECKED,
)

# Intraday (square-off the same day) differs from delivery in three ways: STT is 0.025% and only
# on the sell, stamp duty is 0.003% and only on the buy, and no depository charge is levied
# because the shares never reach the demat account. Exchange, SEBI and GST are unchanged.
_INDIA_INTRADAY_STT = Fee(
    "Securities transaction tax (STT)",
    "tax",
    "A tax the government charges on intraday trades: 0.025% of the value, on the sell side "
    "only. You pay it whether you win or lose.",
    percent=D("0.025"),
    side="sell",
    only_types=_EQ,
    # ETFs are charged no STT in this model (see the delivery rule above); the same page says
    # ETFs that pay STT pay 0.025% on the sell side when traded intraday.
    source=f"{_ZERODHA_CHARGES} and {_GROWW_PRICING} (equity intraday, 0.025% on the sell side)",
    checked=_CHECKED,
)
_INDIA_INTRADAY_STAMP = Fee(
    "Stamp duty",
    "tax",
    "A state tax on buying shares: 0.003% of the value on intraday trades. Only the buyer pays it.",
    percent=D("0.003"),
    side="buy",
    only_types=_EQ_ETF,
    source=f"{_ZERODHA_CHARGES} and {_GROWW_PRICING} (equity intraday, 0.003% on the buy side)",
    checked=_CHECKED,
)
_NSE_EXCHANGE = Fee(
    "Exchange transaction charge",
    "exchange",
    "The exchange's fee for matching your trade: 0.00297%, plus 0.0001% for the "
    "Investor Protection Fund, 0.00307% in all.",
    percent=D("0.00307"),
    only_types=_EQ_ETF,
    source=f"{_GROWW_PRICING} (NSE 0.00297% + IPFT 0.0001%); {_ZERODHA_CHARGES} (NSE 0.00307%)",
    checked=_CHECKED,
)
_BSE_EXCHANGE = Fee(
    "Exchange transaction charge",
    "exchange",
    "The exchange's fee for matching your trade: 0.00375% for the large and mid-cap (A and B group) shares.",
    percent=D("0.00375"),
    only_types=_EQ_ETF,
    # BSE charges differ by scrip group (e.g. 0.1% for X/XT/Z, 1% for P/R/SS/ST);
    # Yahoo does not tell us the group, so every share is treated as group A/B.
    source=f"{_ZERODHA_CHARGES} (BSE 0.00375%), {_GROWW_PRICING} (A, B ... 0.00375%)",
    checked=_CHECKED,
)

# --- Hong Kong -----------------------------------------------------------------------------

_CN_CONNECT = (
    "https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-(Stock-Connect)/"
    "Trading/Transactions"
)

_HKEX_FEES = (
    "https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-(Hong-Kong)/"
    "Trading/Transaction"
)

# --- US ------------------------------------------------------------------------------------

_IBKR_STOCKS = "https://www.interactivebrokers.com/en/pricing/commissions-stocks.php"


@dataclass(frozen=True)
class ShortRule:
    """How selling shares you don't own works on one market. `Market.short_rule` is None where
    retail accounts can't short, and shorting is then simply not offered.

    `style` is the regime: `intraday` must be bought back the same day (India), `overnight` may
    be held and pays a borrow fee (US), `margin` is a leveraged position with a funding rate
    (crypto). Percentages are in percent, like `Fee`.
    """

    style: str
    margin_percent: Decimal  # blocked out of cash, as a percent of the value sold
    borrow_percent_year: Decimal  # yearly borrow or funding cost, on the entry value
    square_off_minutes_before_close: int | None  # closed for you this long before the close
    min_shortable_step: Decimal  # the short part must be a whole multiple of this
    accrual_hours: int = 24  # the borrow or funding cost is charged once per completed period of this
    source: str = ""
    checked: str = ""


@dataclass(frozen=True)
class Market:
    code: str
    name: str  # short, reads in "to trade London shares"
    country: str
    currency: str
    suffixes: tuple[str, ...]  # Yahoo symbol suffixes, with the dot; empty means no suffix
    segment: str  # india | international | crypto
    fees: list[Fee] = field(default_factory=list)
    notes: str = ""
    # exchange_calendars code, or "24/7"; filled in from _CALENDARS below.
    calendar: str = ""
    # Smallest tradable increment of a share; quantity must be a whole multiple of it.
    quantity_step: Decimal = Decimal(1)
    short_rule: ShortRule | None = None
    # Whether an exit can name the lot it closes ("specific") or takes the oldest first ("fifo").
    lot_exits: str = "fifo"
    # The fee table for intraday trades, where it differs from `fees`. None: no such product.
    intraday_fees: list[Fee] | None = None


_NO_TAX = (
    "UNVERIFIED: no transaction tax found in the sources consulted (Tax Foundation 'Financial "
    "Transaction Taxes in Europe, 2026'; BNY Mellon 'A Global View of Financial Transaction "
    "Taxes', undated). A tax not appearing there is not proof that none exists, and no tax "
    "authority publishes a list of taxes it lacks, so no primary source per country was found "
    "on 2026-10-24. Exchange fees are covered by the broker's commission."
)

_RAW_MARKETS = [
    Market(
        "NSE",
        "NSE",
        "India",
        "INR",
        (".NS",),
        "india",
        # NSE transaction charge: 0.00297% + 0.0001% Investor Protection Fund Trust = 0.00307%.
        [
            _NSE_EXCHANGE,
            _INDIA_STT,
            _INDIA_STAMP,
            _INDIA_SEBI,
            _INDIA_GST,
        ],
        "Delivery (cash-and-carry) rates for longs; intraday rates for the shorts you open.",
    ),
    Market(
        "BSE",
        "BSE",
        "India",
        "INR",
        (".BO",),
        "india",
        [
            _BSE_EXCHANGE,
            _INDIA_STT,
            _INDIA_STAMP,
            _INDIA_SEBI,
            _INDIA_GST,
        ],
        "Treats every share as BSE group A or B (0.00375%); other groups charge far more.",
    ),
    Market(
        "US",
        "US",
        "United States",
        "USD",
        (),
        "international",
        [
            Fee(
                "SEC fee",
                "regulatory",
                "A small regulator's fee on sales only: $20.60 per million dollars sold.",
                percent=D("0.00206"),
                side="sell",
                only_types=_EQ_ETF,
                source=f"{_ZERODHA_CHARGES} (SEC 0.00206% on sell), {_IBKR_STOCKS} "
                "(USD 0.0000206 x value of sales)",
                checked=_CHECKED,
            ),
            # FINRA trading activity fee (sells, USD 0.000195/share, max USD 9.79) is left out:
            # both IBKR (rate shown as 0.00) and Zerodha ("paused from 1 October to 31 December
            # 2026") say it is suspended today. Add it back after 2026-12-31.
        ],
        "A symbol with no exchange suffix is treated as US-listed.",
    ),
    Market(
        "LSE",
        "London",
        "United Kingdom",
        "GBP",
        (".L",),
        "international",
        [
            Fee(
                "Stamp duty reserve tax",
                "tax",
                "UK tax on buying shares: 0.5% of the value. Only the buyer pays, and ETFs are exempt.",
                percent=D("0.5"),
                side="buy",
                only_types=_EQ,
                # Simplification: shares on AIM and some foreign companies are exempt in
                # reality, but Yahoo does not say which, so every UK share is charged.
                source="https://www.gov.uk/tax-buy-shares (0.5% when buying shares electronically); "
                "ETF exemption per the owner's brief, not re-checked",
                checked=_CHECKED,
            ),
            Fee(
                "PTM levy",
                "regulatory",
                "A fee that funds the Takeover Panel: GBP 1.50 on any trade over GBP 10,000.",
                flat=D("1.5"),
                above_value=D("10000"),
                only_types=_EQ,
                # Source: 150p per contract where the consideration is over GBP 10,000. It is
                # flat on the whole contract, not a rate on the excess. Buys and sells.
                source="https://www.thetakeoverpanel.org.uk/disclosure/ptm-levy",
                checked=_CHECKED,
            ),
        ],
        "Prices are in pounds (Yahoo's pence are converted).",
    ),
    Market(
        "IRE",
        "Dublin",
        "Ireland",
        "EUR",
        (".IR",),
        "international",
        [
            Fee(
                "Stamp duty",
                "tax",
                "Irish tax on buying shares: 1% of the value. Only the buyer pays.",
                percent=D("1"),
                side="buy",
                only_types=_EQ,
                # ETFs are not charged: Revenue says Irish stamp duty does not apply to transfers of
                # shares in Irish-domiciled ETFs (non-Irish ETFs are not modelled separately).
                # source: https://www.revenue.ie/en/tax-professionals/tdm/income-tax-capital-gains-tax-corporation-tax/part-27/27-01a-03.pdf,
                # checked 2026-10-24
                source="https://www.revenue.ie/en/property/stamp-duty/shares-stocks-marketable-"
                "securities/shares-and-rates.aspx (1% on shares); Irish-domiciled ETFs exempt per "
                "https://www.revenue.ie/en/tax-professionals/tdm/income-tax-capital-gains-tax-corporation-tax/part-27/27-01a-03.pdf",
                checked=_CHECKED,
            )
        ],
    ),
    Market(
        "PAR",
        "Paris",
        "France",
        "EUR",
        (".PA",),
        "international",
        [
            Fee(
                "French financial transaction tax",
                "tax",
                "French tax on buying shares of large French companies: 0.4% of the value. Only buys.",
                percent=D("0.4"),
                side="buy",
                only_types=_EQ,
                # The tax applies only to French companies worth over EUR 1 billion, and
                # Yahoo does not tell us the company's size or nationality. This model charges
                # it on EVERY Paris-listed share, so it overcharges small caps and foreign
                # companies listed in Paris.
                source="https://www.securities-services.societegenerale.com/en/insights/views/news/"
                "financial-transaction-tax/ (0.4% from 1 April 2025; French companies over EUR 1bn)",
                checked=_CHECKED,
            )
        ],
        "The transaction tax is charged on every share here, though in reality only on French "
        "companies worth over EUR 1 billion.",
    ),
    Market(
        "MIL",
        "Milan",
        "Italy",
        "EUR",
        (".MI",),
        "international",
        [
            Fee(
                "Italian financial transaction tax",
                "tax",
                "Italian tax on buying shares of large Italian companies: 0.2% of the value on the "
                "exchange. Only buys.",
                percent=D("0.2"),
                side="buy",
                only_types=_EQ,
                # 0.1% until 31 Dec 2025, 0.2% for regulated-market trades from 1 Jan 2026. In
                # reality it covers only Italian companies above a market-cap threshold (EUR
                # 500m); this model charges every Milan-listed share.
                source="https://www.aoshearman.com/en/insights/italys-2026-budget-law-practical-"
                "takeaways-for-businesses (0.2% regulated markets from 2026-01-01)",
                checked=_CHECKED,
            )
        ],
        "The transaction tax is charged on every share here, though in reality only on Italian "
        "companies above a size threshold.",
    ),
    Market(
        "MAD",
        "Madrid",
        "Spain",
        "EUR",
        (".MC",),
        "international",
        [
            Fee(
                "Spanish financial transaction tax",
                "tax",
                "Spanish tax on buying shares of large Spanish companies: 0.2% of the value. Only buys.",
                percent=D("0.2"),
                side="buy",
                only_types=_EQ,
                # In reality only Spanish companies worth over EUR 1 billion; this model
                # charges every Madrid-listed share.
                source="https://www.europeantax.blog/post/102giva/spain-introduces-financial-"
                "transaction-tax (0.2%, listed Spanish companies over EUR 1bn)",
                checked=_CHECKED,
            )
        ],
        "The transaction tax is charged on every share here, though in reality only on Spanish "
        "companies worth over EUR 1 billion.",
    ),
    Market(
        "HKEX",
        "Hong Kong",
        "Hong Kong",
        "HKD",
        (".HK",),
        "international",
        [
            Fee(
                "Stamp duty",
                "tax",
                "Hong Kong tax of 0.1% on both the buy and the sell, rounded up to the next whole "
                "dollar. ETFs are exempt.",
                percent=D("0.1"),
                only_types=_EQ,
                round_up_to_whole=True,
                source=f"{_HKEX_FEES} (0.1%, both sides, rounded up to the nearest dollar)",
                checked=_CHECKED,
            ),
            Fee(
                "Exchange trading fee",
                "exchange",
                "The exchange's fee: 0.00565% of the value, on each side.",
                percent=D("0.00565"),
                only_types=_EQ_ETF,
                source=f"{_HKEX_FEES} (0.00565% per side, from 1 January 2023)",
                checked=_CHECKED,
            ),
            Fee(
                "SFC transaction levy",
                "regulatory",
                "The securities regulator's levy: 0.0027% of the value, on each side.",
                percent=D("0.0027"),
                only_types=_EQ_ETF,
                source=f"{_HKEX_FEES} (0.0027% per side)",
                checked=_CHECKED,
            ),
            Fee(
                "AFRC transaction levy",
                "regulatory",
                "The accounting regulator's levy: 0.00015% of the value, on each side.",
                percent=D("0.00015"),
                only_types=_EQ_ETF,
                source=f"{_HKEX_FEES} (0.00015% per side, from 1 January 2022)",
                checked=_CHECKED,
            ),
            Fee(
                "CCASS settlement fee",
                "exchange",
                "The clearing house's stock settlement fee: 0.0042% of the value, on each side.",
                percent=D("0.0042"),
                only_types=_EQ_ETF,
                # source: HKSCC circular, checked 2026-10-24 (0.0042% of gross value of an Exchange
                # Trade, no minimum or maximum, for trades from 30 June 2025)
                source="https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/HKSCC/2025/ce_HKSCC_SET_022_2025.pdf",
                checked=_CHECKED,
            ),
        ],
    ),
    Market(
        "SGX",
        "Singapore",
        "Singapore",
        "SGD",
        (".SI",),
        "international",
        [
            Fee(
                "Exchange trading fee",
                "exchange",
                "The exchange's access fee: 0.0075% of the value.",
                percent=D("0.0075"),
                source="https://www.sgx.com/stock-exchange/trading (trading fee 0.0075% of traded value)",
                checked=_CHECKED,
            ),
            Fee(
                "Clearing fee",
                "exchange",
                "The clearing house's fee: 0.0325% of the value.",
                percent=D("0.0325"),
                # UNVERIFIED: an earlier SGX revision (reported by Yahoo Finance Singapore and Lexology)
                # caps this fee at SGD 600 for contracts of SGD 1.5 million or more. The current
                # SGX page (https://www.sgx.com/securities/clearing-information) lists "0.0325% of
                # contract value^" but is rendered by script, so its footnote could not be read on
                # 2026-10-24; large trades may be overcharged.
                source="https://www.sgx.com/securities/clearing-information (0.0325% of traded value)",
                checked=_CHECKED,
            ),
            Fee(
                "GST",
                "gst",
                "Singapore's 9% goods and services tax on the exchange's fees.",
                percent=D("9"),
                on_categories=frozenset({"exchange"}),
                # source: https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/gst-rate-change/gst-rate-change-for-consumers1,
                # checked 2026-10-24 (9% from 1 Jan 2024)
                source="https://www.sgx.com/stock-exchange/trading (prevailing GST); IRAS 9% from "
                "1 Jan 2024: https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/gst-rate-change/"
                "gst-rate-change-for-consumers1",
                checked=_CHECKED,
            ),
        ],
        "No stamp duty applies to listed shares: IRAS exempts the electronic transfer of scripless "
        "shares (https://www.iras.gov.sg/taxes/stamp-duty/for-shares/basics-of-stamp-duty-for-shares/"
        "learning-the-basics-for-shares, checked 2026-10-24).",
    ),
    Market(
        "KOSPI",
        "Seoul (KOSPI)",
        "South Korea",
        "KRW",
        (".KS",),
        "international",
        [
            Fee(
                "Securities transaction tax",
                "tax",
                "Korean tax on selling shares: 0.20% of the value, including a 0.15% rural "
                "development special tax. Only sells.",
                percent=D("0.2"),
                side="sell",
                only_types=_EQ,  # ETFs exempt, checked 2026-10-24:
                # https://www.rbcis.com/en/gmi/global-custody/market-profiles/market.page?dcr=templatedata/globalcustody/marketprofiles/data/south-korea
                source="https://taxsummaries.pwc.com/republic-of-korea/corporate/other-taxes "
                "(0.20% from 1 January 2026, incl. rural development tax); ETFs exempt per RBC "
                "Investor Services' South Korea market profile",
                checked=_CHECKED,
            )
        ],
    ),
    Market(
        "KOSDAQ",
        "Seoul (KOSDAQ)",
        "South Korea",
        "KRW",
        (".KQ",),
        "international",
        [
            Fee(
                "Securities transaction tax",
                "tax",
                "Korean tax on selling shares: 0.20% of the value. Only sells.",
                percent=D("0.2"),
                side="sell",
                only_types=_EQ,  # ETFs exempt (RBC South Korea profile, see KOSPI), checked 2026-10-24
                source="https://taxsummaries.pwc.com/republic-of-korea/corporate/other-taxes "
                "(0.20% for KOSPI and KOSDAQ from 1 January 2026); ETFs exempt per RBC Investor "
                "Services' South Korea market profile",
                checked=_CHECKED,
            )
        ],
    ),
    Market(
        "TWSE",
        "Taiwan",
        "Taiwan",
        "TWD",
        (".TW",),
        "international",
        [
            Fee(
                "Securities transaction tax",
                "tax",
                "Taiwanese tax on selling shares: 0.3% of the value. Only sells.",
                percent=D("0.3"),
                side="sell",
                only_types=_EQ,
                source="https://www.twse.com.tw/en/about/company/guide.html (stocks 0.3% on the seller)",
                checked=_CHECKED,
            ),
            Fee(
                "Securities transaction tax (ETF)",
                "tax",
                "Taiwanese tax on selling ETFs: 0.1% of the value. Only sells.",
                percent=D("0.1"),
                side="sell",
                only_types=frozenset({"etf"}),
                source="https://www.twse.com.tw/en/about/company/guide.html (ETFs 0.1% on the "
                "seller; bond ETFs exempt, not distinguished here)",
                checked=_CHECKED,
            ),
        ],
    ),
    Market(
        "TPEX",
        "Taiwan (OTC)",
        "Taiwan",
        "TWD",
        (".TWO",),
        "international",
        [
            Fee(
                "Securities transaction tax",
                "tax",
                "Taiwanese tax on selling shares: 0.3% of the value. Only sells.",
                percent=D("0.3"),
                side="sell",
                only_types=_EQ,
                # source: https://law-out.mof.gov.tw/EngLawContent.aspx?id=20707, checked 2026-10-24
                source="https://law-out.mof.gov.tw/EngLawContent.aspx?id=20707 (Securities "
                "Transaction Tax Act, Art. 2: 0.3% on shares, paid by the seller; the Act covers "
                "listed and OTC-listed stock alike)",
                checked=_CHECKED,
            ),
            Fee(
                "Securities transaction tax (ETF)",
                "tax",
                "Taiwanese tax on selling ETFs: 0.1% of the value. Only sells.",
                percent=D("0.1"),
                side="sell",
                only_types=frozenset({"etf"}),
                # source: https://law-out.mof.gov.tw/EngLawContent.aspx?id=20707, checked 2026-10-24
                source="https://law-out.mof.gov.tw/EngLawContent.aspx?id=20707 (Securities "
                "Transaction Tax Act, Art. 2: 0.1% on other approved securities, paid by the seller)",
                checked=_CHECKED,
            ),
        ],
    ),
    Market(
        "SSE",
        "Shanghai",
        "China",
        "CNY",
        (".SS",),
        "international",
        [
            Fee(
                "Stamp duty",
                "tax",
                "Chinese tax on selling shares: 0.05% of the value. Only sells; ETFs are exempt.",
                percent=D("0.05"),
                side="sell",
                only_types=_EQ,
                source="https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/"
                "Securities-(Stock-Connect)/Trading/Transactions (0.05% on the seller, ETFs waived)",
                checked=_CHECKED,
            ),
            Fee(
                "Transfer fee",
                "exchange",
                "The clearing house's fee: 0.001% of the value, on each side. Waived for ETFs.",
                percent=D("0.001"),
                only_types=_EQ,
                source="https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/"
                "Securities-(Stock-Connect)/Trading/Transactions (0.001% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Handling fee",
                "exchange",
                "The exchange's fee: 0.00341% of the value, on each side.",
                percent=D("0.00341"),
                only_types=_EQ,
                source=_CN_CONNECT + " (A shares 0.00341% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Handling fee (ETF)",
                "exchange",
                "The exchange's fee for ETFs: 0.004% of the value, on each side.",
                percent=D("0.004"),
                only_types=frozenset({"etf"}),
                source=_CN_CONNECT + " (ETFs 0.004% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Securities management fee",
                "regulatory",
                "The securities regulator's fee: 0.002% of the value, on each side. Waived for ETFs.",
                percent=D("0.002"),
                only_types=_EQ,
                source=_CN_CONNECT + " (A shares 0.002% per purchase or sale, ETFs waived)",
                checked=_CHECKED,
            ),
        ],
    ),
    Market(
        "SZSE",
        "Shenzhen",
        "China",
        "CNY",
        (".SZ",),
        "international",
        [
            Fee(
                "Stamp duty",
                "tax",
                "Chinese tax on selling shares: 0.05% of the value. Only sells; ETFs are exempt.",
                percent=D("0.05"),
                side="sell",
                only_types=_EQ,
                source="https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/"
                "Securities-(Stock-Connect)/Trading/Transactions (0.05% on the seller, ETFs waived)",
                checked=_CHECKED,
            ),
            Fee(
                "Transfer fee",
                "exchange",
                "The clearing house's fee: 0.001% of the value, on each side. Waived for ETFs.",
                percent=D("0.001"),
                only_types=_EQ,
                source="https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/"
                "Securities-(Stock-Connect)/Trading/Transactions (0.001% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Handling fee",
                "exchange",
                "The exchange's fee: 0.00341% of the value, on each side.",
                percent=D("0.00341"),
                only_types=_EQ,
                source=_CN_CONNECT + " (A shares 0.00341% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Handling fee (ETF)",
                "exchange",
                "The exchange's fee for ETFs: 0.004% of the value, on each side.",
                percent=D("0.004"),
                only_types=frozenset({"etf"}),
                source=_CN_CONNECT + " (ETFs 0.004% per purchase or sale)",
                checked=_CHECKED,
            ),
            Fee(
                "Securities management fee",
                "regulatory",
                "The securities regulator's fee: 0.002% of the value, on each side. Waived for ETFs.",
                percent=D("0.002"),
                only_types=_EQ,
                source=_CN_CONNECT + " (A shares 0.002% per purchase or sale, ETFs waived)",
                checked=_CHECKED,
            ),
        ],
    ),
    Market(
        "JSE",
        "Johannesburg",
        "South Africa",
        "ZAR",
        (".JO",),
        "international",
        [
            Fee(
                "Securities transfer tax",
                "tax",
                "South African tax on buying shares: 0.25% of the value. The buyer pays.",
                percent=D("0.25"),
                side="buy",
                # UNVERIFIED: that listed ETF units are charged too. SARS (re-read 2026-10-24) defines
                # a security as a share, a depository interest in a company or a close-corporation
                # member's interest and never mentions ETFs or unit trusts; no SARS or JSE page was
                # found that settles ETF units either way.
                # JSE trading and Strate settlement fees are not recorded.
                source="https://www.sars.gov.za/types-of-tax/securities-transfer-tax/ (0.25%); "
                "buyer pays per https://globallawexperts.com/share-sale-vs-asset-sale-south-africa-tax/",
                checked=_CHECKED,
            )
        ],
    ),
    Market(
        "CRYPTO",
        "Crypto",
        "Global",
        "USD",
        (),
        "crypto",
        [],  # An exchange's own trading fee is the whole cost. No TDS: profit taxes are out of scope.
        "Crypto is chosen by instrument type, not by symbol. No profit taxes or TDS are modelled.",
    ),
    # --- Markets with no transaction tax recorded -----------------------------------------
    # Each carries the UNVERIFIED comment above; their only cost is the broker's commission.
    Market("XETRA", "Germany (Xetra)", "Germany", "EUR", (".DE",), "international", [], _NO_TAX),
    Market("FRA", "Frankfurt", "Germany", "EUR", (".F",), "international", [], _NO_TAX),
    Market("TSE", "Tokyo", "Japan", "JPY", (".T",), "international", [], _NO_TAX),
    Market("TSX", "Toronto", "Canada", "CAD", (".TO",), "international", [], _NO_TAX),
    Market("TSXV", "Toronto Venture", "Canada", "CAD", (".V",), "international", [], _NO_TAX),
    Market("ASX", "Australia", "Australia", "AUD", (".AX",), "international", [], _NO_TAX),
    Market("AMS", "Amsterdam", "Netherlands", "EUR", (".AS",), "international", [], _NO_TAX),
    Market(
        "SIX",
        "Switzerland",
        "Switzerland",
        "CHF",
        (".SW",),
        "international",
        [],
        # source: https://taxsummaries.pwc.com/switzerland/corporate/other-taxes, checked 2026-10-24
        # The securities turnover tax (0.15% Swiss, 0.3% foreign securities) applies when a Swiss
        # securities dealer is a party or intermediary. It is not charged here because none of
        # the brokers modelled is Swiss.
        "A Swiss turnover tax applies when a Swiss securities dealer is involved; none of the "
        "brokers here is, so it is not charged.",
    ),
    Market(
        "BRU",
        "Brussels",
        "Belgium",
        "EUR",
        (".BR",),
        "international",
        [],
        # UNVERIFIED: Belgium's tax on stock exchange transactions (0.35%, max EUR 1,600 per
        # BNY Mellon paper; DEGIRO's help page gives the same) is aimed at Belgian residents and
        # Belgian intermediaries. Only secondary sources (DEGIRO, Curvo) were found for who owes it
        # when the broker is abroad, and no FPS Finance page stating it was found on 2026-10-24.
        "Belgium's stock-exchange tax targets Belgian residents and intermediaries, so it is "
        "not charged (UNVERIFIED).",
    ),
    Market("VIE", "Vienna", "Austria", "EUR", (".VI",), "international", [], _NO_TAX),
    Market("LIS", "Lisbon", "Portugal", "EUR", (".LS",), "international", [], _NO_TAX),
    Market("STO", "Stockholm", "Sweden", "SEK", (".ST",), "international", [], _NO_TAX),
    Market("OSL", "Oslo", "Norway", "NOK", (".OL",), "international", [], _NO_TAX),
    Market("CPH", "Copenhagen", "Denmark", "DKK", (".CO",), "international", [], _NO_TAX),
    Market(
        "HEL",
        "Helsinki",
        "Finland",
        "EUR",
        (".HE",),
        "international",
        [],
        # source: https://www.vero.fi/en/individuals/property/transfer-tax/corporate-stock/,
        # checked 2026-10-24
        # Transfer tax (now 1.5%) is not usually due on listed shares bought through a bank or
        # investment firm.
        "Finland's transfer tax is not usually due on listed shares bought through a broker.",
    ),
    Market("NZX", "New Zealand", "New Zealand", "NZD", (".NZ",), "international", [], _NO_TAX),
    Market("BMV", "Mexico", "Mexico", "MXN", (".MX",), "international", [], _NO_TAX),
]

# Market code -> exchange_calendars code. exchange_calendars has no separate NSE calendar; XBOM
# (the BSE) shares its sessions and holidays. HKEX (XHKG) has a lunch break; the calendar knows.
_CALENDARS = {
    "NSE": "XBOM", "BSE": "XBOM", "US": "XNYS", "LSE": "XLON", "IRE": "XDUB", "PAR": "XPAR",
    "MIL": "XMIL", "MAD": "XMAD", "HKEX": "XHKG", "SGX": "XSES", "KOSPI": "XKRX",
    "KOSDAQ": "XKRX", "TWSE": "XTAI", "TPEX": "XTAI", "SSE": "XSHG", "SZSE": "XSHG",
    "JSE": "XJSE", "CRYPTO": "24/7", "XETRA": "XETR", "FRA": "XFRA", "TSE": "XTKS",
    "TSX": "XTSE", "TSXV": "XTSE", "ASX": "XASX", "AMS": "XAMS", "SIX": "XSWX",
    "BRU": "XBRU", "VIE": "XWBO", "LIS": "XLIS", "STO": "XSTO", "OSL": "XOSL",
    "CPH": "XCSE", "HEL": "XHEL", "NZX": "XNZE", "BMV": "XMEX",
}  # fmt: skip
_STEPS = {"US": Decimal("0.0001"), "CRYPTO": Decimal("0.00000001")}

_DECISIONS = "README, 'Short selling'"
_CHECKED_RULES = "2026-10-24"
_SHORT_RULES = {
    # India: 20% margin as in the plan's decisions; the square-off lead time is typical of the
    # brokers' auto square-off, which runs 10-25 minutes before the close.
    "NSE": ShortRule("intraday", D("20"), D("0"), 10, D("1"), source=_DECISIONS, checked=_CHECKED_RULES),
    "BSE": ShortRule("intraday", D("20"), D("0"), 10, D("1"), source=_DECISIONS, checked=_CHECKED_RULES),
    # US: Reg T initial margin on a short is 50%; borrow is a flat 3% a year (the app has no
    # per-stock borrow rates), charged per day. Whole shares only.
    "US": ShortRule(
        "overnight",
        D("50"),
        D("3"),
        None,
        D("1"),
        source=f"{_DECISIONS} (Reg T 50%, ~3% a year borrow)",
        checked=_CHECKED_RULES,
    ),  # fmt: skip
    # Crypto: 20% margin (5x); funding 0.01% every 8 hours = 0.03% a day = 10.95% a year.
    "CRYPTO": ShortRule(
        "margin",
        D("20"),
        D("10.95"),
        None,
        D("0.00000001"),
        accrual_hours=8,
        source=f"{_DECISIONS} (5x, funding 0.01% per 8 hours)",
        checked=_CHECKED_RULES,
    ),  # fmt: skip
}
# US and crypto let you name the lot you are closing; everywhere else holdings are pooled.
_SPECIFIC_LOTS = {"US", "CRYPTO"}
_INTRADAY_FEES = {
    "NSE": [_NSE_EXCHANGE, _INDIA_INTRADAY_STT, _INDIA_INTRADAY_STAMP, _INDIA_SEBI, _INDIA_GST],
    "BSE": [_BSE_EXCHANGE, _INDIA_INTRADAY_STT, _INDIA_INTRADAY_STAMP, _INDIA_SEBI, _INDIA_GST],
}

_ALL_MARKETS = [
    replace(
        m,
        calendar=_CALENDARS[m.code],
        quantity_step=_STEPS.get(m.code, Decimal(1)),
        short_rule=_SHORT_RULES.get(m.code),
        lot_exits="specific" if m.code in _SPECIFIC_LOTS else "fifo",
        intraday_fees=_INTRADAY_FEES.get(m.code),
    )
    for m in _RAW_MARKETS
]

MARKETS: dict[str, Market] = {m.code: m for m in _ALL_MARKETS}
_BY_SUFFIX: dict[str, Market] = {s: m for m in _ALL_MARKETS for s in m.suffixes}
_US = MARKETS["US"]
_CRYPTO = MARKETS["CRYPTO"]


def market_for(symbol: str, instrument_type: str) -> Market:
    """The market a Yahoo symbol trades on. Crypto is chosen by type, a symbol with no
    exchange suffix is US, and an unknown suffix is refused rather than priced as US."""
    if instrument_type == "crypto":
        return _CRYPTO
    if "." not in symbol:
        return _US
    suffix = "." + symbol.rsplit(".", 1)[1].upper()
    found = _BY_SUFFIX.get(suffix)
    if found is None:
        raise UnsupportedMarket(
            f"{symbol} trades on an exchange ({suffix}) whose trading costs aren't recorded yet, "
            "so it can't be traded here."
        )
    return found
