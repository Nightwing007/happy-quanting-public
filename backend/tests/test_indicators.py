import math

import pandas as pd
import pytest

from app.indicators import ema, rsi, sma


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
