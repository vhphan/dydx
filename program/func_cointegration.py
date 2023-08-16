import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

from program.constants import WINDOW


#  function to calculate half life
# https://www.pythonforfinance.net/2016/05/09/python-backtesting-mean-reversion-part-2/
def calculate_half_life(spread) -> int:
    df_spread = pd.DataFrame(spread, columns=['spread'])
    spread_lag = df_spread.spread.shift(1)
    spread_lag.iloc[0] = spread_lag.iloc[1]
    spread_ret = df_spread.spread - spread_lag
    spread_ret.iloc[0] = spread_ret.iloc[1]
    spread_lag2 = sm.add_constant(spread_lag)
    model = sm.OLS(spread_ret, spread_lag2)
    res = model.fit()
    half_life = int(round(-np.log(2) / res.params[1], 0))
    return half_life


# function to calculate z-score of the spread
def calculate_zscore(spread) -> pd.Series:
    spread_series = pd.Series(spread)
    mean = spread_series.rolling(WINDOW)
    std = spread_series.rolling(WINDOW)
    zscore = (spread_series - mean) / std
    return zscore


# function to calculate cointegration of two series
# function returns a flag indicating whether the two series are cointegrated
# function also returns the hedge ratio and half life of the spread
def calculate_cointegration(series1, series2) -> (int, float, int):
    series1 = np.array(series1).astype(np.float)
    series2 = np.array(series2).astype(np.float)
    coint_res = coint(series1, series2)
    coint_t = coint_res[0]
    p_value = coint_res[1]
    critical_value = coint_res[2][1]
    model = sm.OLS(series1, series2).fit()
    hedge_ratio: float = model.params[0]
    half_life: int = calculate_half_life(series1 - hedge_ratio * series2)
    coint_flag: int = 1 if (coint_t < critical_value) and (p_value < 0.05) else 0

    return coint_flag, hedge_ratio, half_life
