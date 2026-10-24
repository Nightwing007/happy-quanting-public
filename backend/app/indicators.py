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


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average true range, Wilder's way: the first value is the plain mean of the first `period`
    true ranges, every later one is (previous * (period - 1) + true range) / period. Values before
    a full window are NaN."""
    prev_close = close.shift(1)
    # The first bar has no previous close, so its true range is just high - low (max skips NaN).
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    out = pd.Series(float("nan"), index=true_range.index, dtype=float)
    if len(true_range) < period:
        return out
    current = float(true_range.iloc[:period].mean())
    out.iloc[period - 1] = current
    for i in range(period, len(true_range)):
        current = (current * (period - 1) + float(true_range.iloc[i])) / period
        out.iloc[i] = current
    return out


def bollinger(s: pd.Series, period: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(middle, upper, lower): the simple average and k standard deviations either side. The
    deviation is the population one (divide by N), as Bollinger defined the bands."""
    mid = sma(s, period)
    spread = s.rolling(period).std(ddof=0) * k
    return mid, mid + spread, mid - spread


def highest(s: pd.Series, period: int) -> pd.Series:
    """The highest value of the last `period` bars, the current one included."""
    return s.rolling(period).max()


def lowest(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period).min()
