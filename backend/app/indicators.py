"""Technical indicators. Keep these pure (Series in, Series out): a later backtester reuses them."""

import pandas as pd

# Indicators are chart values, not money, so floats are fine here. Don't "fix" this to Decimal.


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    # Wilder's smoothing is an EMA with alpha = 1/period (not the span-based alpha of ema()).
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss)
    # No losses at all means a pure uptrend: 100 (guards against 0/0 and inf quirks).
    out[(loss == 0) & (gain > 0)] = 100.0
    return out
