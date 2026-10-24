"""The five company metrics (and a coin's four), each shown against a sector's usual range.

The ranges are hand-written rules of thumb, not a feed: Yahoo publishes no sector benchmarks.
They are rounded bands drawn from Aswath Damodaran's (NYU Stern) US industry datasets, dated
January 2026 and checked 2026-10-24: pedata (P/E), pbvdata (P/B and ROE) and dbtfund (debt).
Yahoo's eleven sectors are coarser than Damodaran's ~95 industries, so each band is a judgement
across the industries that fall in the sector: wide enough to hold most of them, rounded to
numbers a person can remember. Edit the tables to correct a figure; no logic changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.market_data.base import Fundamentals
from app.schemas import MetricOut, MetricRangeOut, MetricsOut, OmittedMetricOut

BELOW, TYPICAL, ABOVE = "below usual", "typical", "above usual"

NOTE = (
    "Sector ranges are rules of thumb from NYU Stern (Damodaran) industry data, not a live feed. "
    "Yahoo Finance publishes no sector benchmarks."
)
NOT_APPLICABLE_NOTE = (
    "Company metrics apply to individual companies and coins, not to indexes, funds or currencies."
)

FINANCIAL = "Financial Services"
DE_FINANCIAL_REASON = (
    "Banks borrow as their raw material, so debt-to-equity says little; "
    "regulators look at capital adequacy instead."
)

Range = tuple[Decimal, Decimal]


def _r(low: str, high: str) -> Range:
    return Decimal(low), Decimal(high)


# Yahoo's sector names. A symbol whose sector is missing or not here uses "default".
SECTORS = (
    "Technology",
    "Financial Services",
    "Healthcare",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Industrials",
    "Energy",
    "Basic Materials",
    "Communication Services",
    "Utilities",
    "Real Estate",
)


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str  # "x" or "%"
    explanation: str
    better: str  # lower | higher | depends
    below_meaning: str
    above_meaning: str
    ranges: dict[str, Range]  # sector -> (low, high), plus "default"


# Trailing P/E. Damodaran pedata, January 2026, "Aggregate Mkt Cap / Trailing Net Income (only
# money-making firms)" and the trailing/forward columns, rounded; checked 2026-10-24.
# E.g. Technology: software 37.5, semiconductors 48.8, computers 34.3, electronics 40.2.
# Financial services: regional banks 12.6, money-centre banks 14.2, P&C insurers 11.8, non-bank
# financials 22.1, brokers 19.8.
PE = MetricDef(
    key="pe",
    label="P/E",
    unit="x",
    explanation=(
        "Price divided by the last twelve months of profit per share: roughly how many years of "
        "today's profit the share price pays for."
    ),
    better="lower",
    below_meaning=(
        "Often means the market expects profits to shrink or sees extra risk, though it can also "
        "mean the shares are cheap. The number alone can't tell which."
    ),
    above_meaning=(
        "Often means the market expects profits to grow faster than usual for the sector, or "
        "that the shares are pricey for what they earn today."
    ),
    ranges={
        "Technology": _r("20", "40"),
        "Financial Services": _r("8", "22"),
        "Healthcare": _r("15", "30"),  # pharma 25.0, products 30.4, hospitals 15.6, biotech 32.1
        "Consumer Cyclical": _r("12", "28"),  # retail 22-33, apparel 27.1, homebuilding 11.3
        "Consumer Defensive": _r("15", "25"),  # food 16.5, household 19.7, tobacco 19.8, grocery 25.2
        "Industrials": _r("14", "30"),  # transport 13.4, rails 20.9, machinery 26.6, aerospace 35.3
        "Energy": _r("9", "20"),  # E&P 12.7, distribution 18.6, integrated 19.0, oilfield 19.4
        "Basic Materials": _r("12", "25"),  # packaging 13.9, building 17.1, chemicals 18-23, mining 29.5
        "Communication Services": _r("10", "28"),  # broadcasting 13.5, telecom 8-19.5, advertising 25.5
        "Utilities": _r("15", "24"),  # general 20.5, water 20.2, power 21.0
        "Real Estate": _r("12", "35"),  # development 13.4, general 19.4, REITs 28.1 (REITs are judged by FFO)
        "default": _r("12", "30"),  # whole market 26.6, without financials 28.9
    },
)

# Price to book. Damodaran pbvdata, January 2026, PBV column, rounded; checked 2026-10-24.
# Technology: software 9.1, semiconductors 13.3, electronics 5.0 (Computers/Peripherals at 34 is
# an outlier from a few huge buyback-shrunk equity bases and is left out of the band).
PB = MetricDef(
    key="pb",
    label="P/B",
    unit="x",
    explanation=(
        "Share price divided by book value per share (assets minus debts, as the accounts record "
        "them): what the market pays for each rupee or dollar of net worth."
    ),
    better="lower",
    below_meaning=(
        "The market values the company near or below its accounting net worth. That can signal "
        "doubt about the assets or future profits, or a bargain."
    ),
    above_meaning=(
        "Investors pay well above net worth, usually for strong earning power or for things the "
        "balance sheet barely counts, such as brands and software."
    ),
    ranges={
        "Technology": _r("3", "12"),
        "Financial Services": _r("0.8", "2.5"),  # regional banks 1.1, money-centre 1.6, life ins. 1.4
        "Healthcare": _r("2.5", "7"),  # products 4.4, hospitals 5.6, pharma 6.6
        "Consumer Cyclical": _r("2", "8"),  # apparel 3.9, retail 7.2-7.3, autos 7.7
        "Consumer Defensive": _r("1.5", "6"),  # food 1.8, grocery 3.9, household 5.9, soft drinks 6.9
        "Industrials": _r("2.5", "7"),  # air 2.8, machinery 4.5, transport 4.8, aerospace 7.9
        "Energy": _r("1", "2.5"),  # E&P 1.4, integrated 1.7
        "Basic Materials": _r("1", "3.5"),  # chemicals 1.1-2.5, steel 1.9, paper 1.8, mining 4.3
        "Communication Services": _r("1.5", "5"),  # telecom 1.6, wireless 3.5, entertainment 4.8
        "Utilities": _r("1.2", "2.5"),  # general 1.8, power 2.3
        "Real Estate": _r("0.8", "2.5"),  # development 1.0, REITs 2.0, services 3.1
        "default": _r("1.5", "5"),  # whole market 4.6, without financials 5.1
    },
)

# Return on equity, in percent. Damodaran pbvdata, January 2026, ROE column, rounded;
# checked 2026-10-24. Technology: software 29.6, semiconductors 31.4, electronics 12.6.
ROE = MetricDef(
    key="roe",
    label="Return on equity",
    unit="%",
    explanation=(
        "Yearly profit as a share of the money shareholders have in the business: how much the "
        "company earns on what is theirs."
    ),
    better="higher",
    below_meaning=(
        "Profits are small for the shareholders' money invested, or the business is in a poor "
        "patch."
    ),
    above_meaning=(
        "The company earns a lot on shareholders' money. A very high figure can also come from "
        "heavy borrowing or a small equity base, so read it next to debt-to-equity."
    ),
    ranges={
        "Technology": _r("12", "30"),
        "Financial Services": _r("9", "18"),  # regional banks 9.8, money-centre 12.9, life ins. 12.9
        "Healthcare": _r("10", "25"),  # products 11.3, pharma 24.0 (hospitals 50.8 is an outlier)
        "Consumer Cyclical": _r("8", "25"),  # apparel 10.4, retail 26-30, autos 3.2
        "Consumer Defensive": _r("8", "25"),  # grocery 12.9, household 27.0, soft drinks 30.9, food 4.6
        "Industrials": _r("10", "22"),  # air 14.2, aerospace 15.3, machinery 16.4
        "Energy": _r("6", "15"),  # integrated 10.0, E&P 12.2
        "Basic Materials": _r("4", "15"),  # steel 3.7, paper 7.0, mining 17.8, chemicals -8 to 3.5
        "Communication Services": _r("6", "20"),  # entertainment 6.1, wireless 16.1, telecom 19.8
        "Utilities": _r("7", "13"),  # general 10.4, power 12.4
        "Real Estate": _r("3", "10"),  # services 3.3, REITs 5.0, development 5.1
        "default": _r("8", "20"),  # whole market 17.2, without financials 16.4
    },
)

# Debt to equity, as a ratio of book debt to book equity. Damodaran dbtfund, January 2026, gives
# "Book Debt to Capital"; D/E = x / (1 - x), so 34% becomes 0.52. Book (not market) because Yahoo's
# figure is book-based. Checked 2026-10-24. Financial Services has no range: the metric is omitted.
DE = MetricDef(
    key="de",
    label="Debt-to-equity",
    unit="x",
    explanation=(
        "Total borrowings divided by shareholders' equity: how many rupees or dollars of debt the "
        "company carries for each one of its own."
    ),
    better="lower",
    below_meaning=(
        "Little borrowing relative to shareholders' money: usually steadier through bad years, "
        "and sometimes a sign of slower growth."
    ),
    above_meaning=(
        "More borrowing than usual for the sector: profits get magnified in good years, while "
        "interest payments weigh more heavily in bad ones."
    ),
    ranges={
        "Technology": _r("0.2", "0.9"),  # semis 0.34, electronics 0.51, software 0.52, computers 1.6
        "Healthcare": _r("0.3", "1.2"),  # products 0.56, pharma 0.93 (hospitals 3.2 is an outlier)
        "Consumer Cyclical": _r("0.4", "1.5"),  # retail 0.58, apparel 1.29, autos 1.52
        "Consumer Defensive": _r("0.4", "1.5"),  # food 0.79, household 1.04, soft drinks 1.34, grocery 2.0
        "Industrials": _r("0.5", "1.6"),  # machinery 0.65, aerospace 1.21, transport 1.75
        "Energy": _r("0.2", "0.8"),  # integrated 0.21, E&P 0.50
        "Basic Materials": _r("0.3", "1.0"),  # steel 0.43, mining 0.44, chemicals 0.7-1.1
        "Communication Services": _r("0.5", "1.8"),  # entertainment 0.75, telecom 1.56, wireless 1.83
        "Utilities": _r("1.0", "2.0"),  # general 1.37, power 1.68
        "Real Estate": _r("0.8", "2.0"),  # development 1.0, REITs 1.7
        "default": _r("0.3", "1.5"),  # whole market without financials 0.93
    },
)

# Dividend yield, in percent. UNVERIFIED for every sector: Damodaran's dividend dataset (divfund,
# January 2026) publishes payout ratios, not yields, so these are sensible rounded rules of thumb
# for large listed companies, not figures read from a table.
DIVIDEND_YIELD = MetricDef(
    key="dividend_yield",
    label="Dividend yield",
    unit="%",
    explanation=(
        "Cash dividends paid per share over a year, as a percentage of the share price: what "
        "holding the share pays you each year before any change in its price."
    ),
    better="depends",
    below_meaning=(
        "Pays out little: the company may be keeping profits to grow, or the share price is "
        "high relative to the dividend."
    ),
    above_meaning=(
        "Pays out a lot for its price. A high yield can also come from a share price that has "
        "fallen, and from a payout the company may not be able to keep up."
    ),
    ranges={
        "Technology": _r("0", "1.5"),  # UNVERIFIED
        "Financial Services": _r("1.5", "4"),  # UNVERIFIED
        "Healthcare": _r("0.5", "3"),  # UNVERIFIED
        "Consumer Cyclical": _r("0", "2"),  # UNVERIFIED
        "Consumer Defensive": _r("1.5", "4"),  # UNVERIFIED
        "Industrials": _r("0.5", "3"),  # UNVERIFIED
        "Energy": _r("2", "6"),  # UNVERIFIED
        "Basic Materials": _r("1", "4"),  # UNVERIFIED
        "Communication Services": _r("0.5", "5"),  # UNVERIFIED
        "Utilities": _r("2.5", "5"),  # UNVERIFIED
        "Real Estate": _r("3", "7"),  # UNVERIFIED
        "default": _r("0.5", "4"),  # UNVERIFIED
    },
)

TYPICAL_MEANING = "Within the usual range for its sector, so nothing about it stands out."


def assess(value: Decimal, usual: Range) -> str:
    """Where a figure sits against a (low, high) band. The ends of the band count as typical."""
    low, high = usual
    if value < low:
        return BELOW
    if value > high:
        return ABOVE
    return TYPICAL


def meaning_for(metric: MetricDef, assessment: str) -> str:
    return {BELOW: metric.below_meaning, ABOVE: metric.above_meaning}.get(assessment, TYPICAL_MEANING)


def _trim(value: Decimal) -> Decimal:
    """Two decimals, then no trailing zeros: 24.80 -> 24.8, 30.00 -> 30. The Money serializer
    prints this without an exponent, so 1.2E+12 goes out as "1200000000000"."""
    return value.quantize(Decimal("0.01")).normalize()


@dataclass(frozen=True)
class _Equity:
    metric: MetricDef
    pick: Callable[[Fundamentals], Decimal | None]
    needs_positive: bool  # P/E and P/B are meaningless at or below zero; ROE is fine negative


_EQUITY_METRICS = (
    _Equity(PE, lambda f: f.trailing_pe, True),
    _Equity(PB, lambda f: f.price_to_book, True),
    _Equity(ROE, lambda f: f.return_on_equity, False),
    _Equity(DE, lambda f: f.debt_to_equity, True),
    _Equity(DIVIDEND_YIELD, lambda f: f.dividend_yield, True),
)


def _equity_metrics(f: Fundamentals) -> tuple[list[MetricOut], list[OmittedMetricOut]]:
    sector = f.sector if f.sector in SECTORS else None
    label = sector or "All sectors"
    metrics: list[MetricOut] = []
    omitted: list[OmittedMetricOut] = []
    for entry in _EQUITY_METRICS:
        metric = entry.metric
        if metric is DE and sector == FINANCIAL:
            omitted.append(OmittedMetricOut(key=metric.key, label=metric.label, reason=DE_FINANCIAL_REASON))
            continue
        value = entry.pick(f)
        # A metric with no figure is left out of the list entirely, not sent as null.
        if value is None or (entry.needs_positive and value <= 0):
            continue
        low, high = metric.ranges[sector or "default"]
        assessment = assess(value, (low, high))
        metrics.append(
            MetricOut(
                key=metric.key,
                label=metric.label,
                value=_trim(value),
                unit=metric.unit,  # type: ignore[arg-type]
                display_hint="multiple" if metric.unit == "x" else "percent",
                assessment=assessment,  # type: ignore[arg-type]
                range=MetricRangeOut(low=low, high=high, label=label),
                explanation=metric.explanation,
                better=metric.better,  # type: ignore[arg-type]
                meaning=meaning_for(metric, assessment),
                if_below=metric.below_meaning,
                if_above=metric.above_meaning,
            )
        )
    return metrics, omitted


def _crypto_metrics(f: Fundamentals) -> list[MetricOut]:
    metrics: list[MetricOut] = []

    def add(key, label, value, unit, hint, explanation, meaning, range_=None):
        metrics.append(
            MetricOut(
                key=key,
                label=label,
                value=_trim(value),
                unit=unit,
                display_hint=hint,
                assessment=None,  # there is no sector band for a coin
                range=range_,
                explanation=explanation,
                better="depends",
                meaning=meaning,
                if_below=None,
                if_above=None,
            )
        )

    if f.market_cap is not None and f.market_cap > 0:
        add(
            "market_cap", "Market cap", f.market_cap, "currency", "amount",
            "The price of one coin times the number of coins in circulation: the market's value "
            "of the whole coin.",
            "A bigger market cap usually means a more established, harder-to-move coin; a smaller "
            "one can swing much further on little money.",
        )
    if f.volume_24h is not None and f.volume_24h > 0:
        add(
            "volume_24h", "24-hour volume", f.volume_24h, "currency", "amount",
            "The value of the coin traded over the last 24 hours.",
            "High volume next to market cap means easy buying and selling; very low volume means "
            "prices can jump on small orders.",
        )
    if f.circulating_supply is not None and f.circulating_supply > 0:
        add(
            "circulating_supply", "Circulating supply", f.circulating_supply, "units", "count",
            "How many coins are in public hands right now.",
            "Compare it with the maximum supply, where one exists: coins not yet released can "
            "dilute holders later.",
        )
    low, high, price = f.fifty_two_week_low, f.fifty_two_week_high, f.price
    if low is not None and high is not None and price is not None and high > low:
        # Where today's price sits between the year's low and high: (price - low) / (high - low).
        # Clamped, since a fresh high or low can land just outside a stale 52-week figure.
        position = min(max((price - low) / (high - low) * 100, Decimal(0)), Decimal(100))
        add(
            "range_position", "Position in 52-week range", position, "%", "position",
            "Where the price sits between the lowest (0%) and highest (100%) price of the past year.",
            "Near 100% means close to the year's peak; near 0% means close to its bottom. It says "
            "where the price has been, not where it is going.",
            MetricRangeOut(low=_trim(low), high=_trim(high), label="52-week"),
        )
    return metrics


def build_metrics(f: Fundamentals, kind: str, currency: str) -> MetricsOut:
    """`kind` is "equity", "crypto" or "other" (indexes, funds, currencies: nothing to show)."""
    if kind == "equity":
        metrics, omitted = _equity_metrics(f)
        note = NOTE
    elif kind == "crypto":
        metrics, omitted = _crypto_metrics(f), []
        note = "Coins have no sector ranges, so these are shown without a verdict."
    else:
        metrics, omitted, note = [], [], NOT_APPLICABLE_NOTE
    return MetricsOut(
        symbol=f.symbol,
        kind=kind,  # type: ignore[arg-type]
        sector=f.sector if kind == "equity" else None,
        currency=currency,
        metrics=metrics,
        omitted=omitted,
        note=note,
    )
