import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app import indicators as ind
from app.api.deps import Provider, SymbolParam, clean_symbol
from app.market_data.base import ALLOWED_RANGES, Fundamentals
from app.metrics import build_metrics
from app.schemas import (
    BarOut,
    BarsOut,
    IndicatorPoint,
    IndicatorSeriesOut,
    InstrumentOut,
    MetricsOut,
    QuoteOut,
)

router = APIRouter(prefix="/api/market", tags=["market"])

# A huge period would make the rolling/ewm window absurd for no benefit and hang the request.
MIN_PERIOD, MAX_PERIOD = 2, 400
_DEFAULT_PERIOD = {"rsi": 14}
_PANES = {"sma": "price", "ema": "price", "rsi": "own"}
_FUNCS = {"sma": ind.sma, "ema": ind.ema, "rsi": ind.rsi}


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def parse_indicators(spec: str) -> list[tuple[str, int]]:
    parsed: list[tuple[str, int]] = []
    for token in spec.split(","):
        token = token.strip().lower()
        if not token:
            continue
        kind, _, raw_period = token.partition(":")
        if kind not in _PANES:
            raise _bad_request(
                f"Indicator '{kind}' isn't available. Choose one of: {', '.join(_PANES)}."
            )
        if raw_period:
            if not raw_period.isdigit():
                raise _bad_request(
                    f"Indicator '{token}' is malformed. Use the form {kind}:20 with a whole-number period."
                )
            period = int(raw_period)
        elif kind in _DEFAULT_PERIOD:
            period = _DEFAULT_PERIOD[kind]
        else:
            raise _bad_request(f"Indicator '{kind}' needs a period, e.g. {kind}:20.")
        if not MIN_PERIOD <= period <= MAX_PERIOD:
            raise _bad_request(
                f"Period {period} for {kind.upper()} isn't allowed. "
                f"Use a whole number from {MIN_PERIOD} to {MAX_PERIOD}."
            )
        parsed.append((kind, period))
    return parsed


@router.get("/search", response_model=list[InstrumentOut])
def search(provider: Provider, q: str = Query(min_length=1, max_length=64)):
    return [InstrumentOut.from_instrument(i) for i in provider.search(q)]


@router.get("/quote", response_model=QuoteOut)
def quote(provider: Provider, symbol: SymbolParam):
    return QuoteOut.from_quote(provider.get_quote(clean_symbol(symbol)))


@router.get("/metrics", response_model=MetricsOut)
def metrics(provider: Provider, symbol: SymbolParam):
    symbol = clean_symbol(symbol)
    quote = provider.get_quote(symbol)  # also the 404 for an unknown symbol, and the quote type
    # Indexes, funds and currencies answer 200 with an empty list and a note, so the card can say
    # why it is empty instead of the page showing an error.
    kind = quote.type if quote.type in ("equity", "crypto") else "other"
    fundamentals = provider.get_fundamentals(symbol) if kind != "other" else None
    if fundamentals is None:
        fundamentals = Fundamentals(symbol=symbol, sector=None, industry=None, currency=quote.currency)
    return build_metrics(fundamentals, kind, quote.currency)


@router.get("/bars", response_model=BarsOut)
def bars(
    provider: Provider,
    symbol: SymbolParam,
    interval: str = "1d",
    range: str = "6mo",  # noqa: A002 - the public query parameter is called "range"
    indicators: str = "",
):
    # Validate everything before fetching: a bad request must never cost an upstream call.
    if interval not in ALLOWED_RANGES:
        raise _bad_request(
            f"Interval '{interval}' isn't available. Choose one of: {', '.join(ALLOWED_RANGES)}."
        )
    if range not in ALLOWED_RANGES[interval]:
        raise _bad_request(
            f"Range '{range}' isn't available for {interval} bars. "
            f"Choose one of: {', '.join(ALLOWED_RANGES[interval])}."
        )
    wanted = parse_indicators(indicators)

    symbol = clean_symbol(symbol)
    raw_bars = provider.get_bars(symbol, interval, range)
    currency = provider.get_quote(symbol).currency

    # Indicators are chart values, not money, so floats are fine here.
    closes = pd.Series([float(b.close) for b in raw_bars])
    series: list[IndicatorSeriesOut] = []
    for kind, period in wanted:
        values = _FUNCS[kind](closes, period)
        points = [
            IndicatorPoint(time=b.time, value=float(v))
            for b, v in zip(raw_bars, values, strict=True)
            if pd.notna(v)
        ]
        series.append(
            IndicatorSeriesOut(
                name=kind,
                period=period,
                pane=_PANES[kind],
                label=f"{kind.upper()} {period}",
                points=points,
            )
        )

    return BarsOut(
        symbol=symbol,
        interval=interval,
        range=range,
        currency=currency,
        bars=[BarOut(**vars(b)) for b in raw_bars],
        indicators=series,
    )
