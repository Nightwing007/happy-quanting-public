import math

import pandas as pd
import pytest

from app.indicators import atr, bollinger, ema, highest, lowest, rsi, sma


def test_sma_window_3():
    # Windows: (1,2,3)->2, (2,3,4)->3, (3,4,5)->4; first two have no full window.
    result = sma(pd.Series([1, 2, 3, 4, 5]), 3)
    assert math.isnan(result[0]) and math.isnan(result[1])
    assert list(result[2:]) == [2, 3, 4]


def test_ema_period_3():
    # span 3 -> alpha = 2/(3+1) = 0.5. e0 = 1; e1 = 0.5*2 + 0.5*1 = 1.5; e2 = 0.5*3 + 0.5*1.5 = 2.25.
    assert list(ema(pd.Series([1, 2, 3]), 3)) == [1, 1.5, 2.25]


def test_rsi_strictly_rising_is_100():
    result = rsi(pd.Series([1, 2, 3, 4, 5, 6]), period=3)
    assert math.isnan(result[0])
    assert all(v == 100 for v in result[1:])


def test_rsi_mixed_series_wilder():
    # period 2 -> alpha = 0.5. closes 10, 11, 10, 12 -> changes +1, -1, +2.
    # gains  (smoothed): g1 = 1,   g2 = 0.5*0 + 0.5*1 = 0.5,  g3 = 0.5*2 + 0.5*0.5 = 1.25
    # losses (smoothed): l1 = 0,   l2 = 0.5*1 + 0.5*0 = 0.5,  l3 = 0.5*0 + 0.5*0.5 = 0.25
    # i=1: no losses -> 100.   i=2: RS = 0.5/0.5 = 1 -> 100 - 100/2 = 50.
    # i=3: RS = 1.25/0.25 = 5 -> 100 - 100/6 = 83.3333.
    result = rsi(pd.Series([10, 11, 10, 12]), period=2)
    assert result[1] == 100
    assert result[2] == pytest.approx(50)
    assert result[3] == pytest.approx(100 - 100 / 6)


def test_atr_wilder():
    # high 10,12,13  low 8,9,10  close 9,11,12.
    # True ranges: bar0 = 10-8 = 2 (no previous close); bar1 = max(12-9, |12-9|, |9-9|) = 3;
    # bar2 = max(13-10, |13-11|, |10-11|) = 3.
    # Period 2: first ATR (bar1) = (2+3)/2 = 2.5; next = (2.5*1 + 3)/2 = 2.75.
    result = atr(pd.Series([10, 12, 13]), pd.Series([8, 9, 10]), pd.Series([9, 11, 12]), 2)
    assert math.isnan(result[0])
    assert list(result[1:]) == [2.5, 2.75]


def test_atr_gap_uses_previous_close():
    # A gap up: bar1 low 20 is far above the previous close 10, so TR = |high - prev close| = 12,
    # not the bar's own range of 2. Period 1 -> ATR is the true range itself.
    result = atr(pd.Series([11, 22]), pd.Series([9, 20]), pd.Series([10, 21]), 1)
    assert list(result) == [2, 12]


def test_bollinger_population_deviation():
    # 2,4,4,4,5,5,7,9: mean 5, squared gaps 9+1+1+1+0+0+4+16 = 32, /8 = 4, deviation 2 exactly.
    mid, upper, lower = bollinger(pd.Series([2, 4, 4, 4, 5, 5, 7, 9]), 8, 1.5)
    assert math.isnan(mid[6]) and math.isnan(upper[6])
    assert (mid[7], upper[7], lower[7]) == (5, 8, 2)  # 5 +/- 1.5 * 2


def test_highest_and_lowest_rolling():
    # Windows of 3 over 1,3,2,5,4: (1,3,2) (3,2,5) (2,5,4) -> highs 3,5,5 and lows 1,2,2.
    s = pd.Series([1, 3, 2, 5, 4])
    assert list(highest(s, 3)[2:]) == [3, 5, 5]
    assert list(lowest(s, 3)[2:]) == [1, 2, 2]
    assert math.isnan(highest(s, 3)[1])
