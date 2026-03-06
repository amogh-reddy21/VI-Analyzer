import numpy as np
import pandas as pd
import yfinance as yf
from config import Config


def fetch_price_history(ticker: str, period: str = None, interval: str = None) -> pd.DataFrame:
    """
    Fetch OHLCV data for a ticker via yfinance.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume.
    Raises ValueError if the ticker is invalid or no data returned.
    """
    period = period or Config.DEFAULT_PERIOD
    interval = interval or Config.DEFAULT_INTERVAL

    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if df.empty:
        raise ValueError(f"No price data found for ticker '{ticker}'. Check the symbol.")

    # yfinance sometimes returns MultiIndex columns — flatten them
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    return df


def compute_historical_volatility(df: pd.DataFrame, window: int = 21) -> dict:
    """
    Compute annualised historical volatility (HV) from close prices.

    HV = std(log returns over `window` days) * sqrt(252)

    Returns a dict with:
      - current_hv:    most recent rolling HV (annualised, as a %)
      - hv_series:     list of {date, hv} for the full lookback
      - mean_hv:       mean HV over the period
      - min_hv / max_hv
    """
    closes = df["Close"].dropna()
    log_returns = np.log(closes / closes.shift(1)).dropna()

    rolling_std = log_returns.rolling(window=window).std().dropna()
    hv_annualised = rolling_std * np.sqrt(Config.ANNUALIZATION_FACTOR) * 100  # as percentage

    hv_series = [
        {"date": str(date.date()), "hv": round(float(val), 4)}
        for date, val in hv_annualised.items()
    ]

    return {
        "current_hv": round(float(hv_annualised.iloc[-1]), 4),
        "mean_hv":    round(float(hv_annualised.mean()), 4),
        "min_hv":     round(float(hv_annualised.min()), 4),
        "max_hv":     round(float(hv_annualised.max()), 4),
        "window_days": window,
        "hv_series":  hv_series,
    }


def compute_price_summary(df: pd.DataFrame) -> dict:
    """
    Return a summary of recent price action: latest close, % change,
    52-week high/low, and average daily volume.
    """
    closes = df["Close"].dropna()
    latest_close  = float(closes.iloc[-1])
    prev_close    = float(closes.iloc[-2]) if len(closes) > 1 else latest_close
    pct_change    = round((latest_close - prev_close) / prev_close * 100, 4)

    high_52w = round(float(closes.tail(252).max()), 4)
    low_52w  = round(float(closes.tail(252).min()), 4)

    avg_volume = (
        round(float(df["Volume"].tail(20).mean()), 0)
        if "Volume" in df.columns else None
    )

    price_series = [
        {"date": str(d.date()), "close": round(float(v), 4)}
        for d, v in closes.tail(252).items()
    ]

    return {
        "latest_close":  round(latest_close, 4),
        "pct_change_1d": pct_change,
        "high_52w":      high_52w,
        "low_52w":       low_52w,
        "avg_volume_20d": avg_volume,
        "price_series":  price_series,
    }
