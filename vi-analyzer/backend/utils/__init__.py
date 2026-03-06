import re
import numpy as np
import pandas as pd
import yfinance as yf
from curl_cffi import requests as cffi_requests
from config import Config
import logging
import time

logger = logging.getLogger(__name__)


def _make_session() -> cffi_requests.Session:
    """Create a curl_cffi session impersonating Chrome 124."""
    return cffi_requests.Session(impersonate="chrome124")


def _get_crumb(session: cffi_requests.Session) -> str | None:
    """
    Warm the session cookies by visiting the Yahoo Finance quote page and
    extract the crumb token directly from the HTML.

    The /v1/test/getcrumb API endpoint is rate-limited on shared IPs (e.g.
    Render free tier), so we parse the crumb from the page source instead —
    Yahoo Finance embeds it in a JSON blob in every quote page response.

    Returns the crumb string, or None on failure.
    """
    try:
        r = session.get(
            "https://finance.yahoo.com/quote/AAPL/",
            timeout=20,
            allow_redirects=True,
        )
        if r.status_code == 200:
            matches = re.findall(r'"crumb":"([^"]{5,25})"', r.text)
            if matches:
                logger.debug("Extracted crumb from HTML: %s", matches[0])
                return matches[0]
    except Exception as e:
        logger.warning("_get_crumb failed: %s", e)
    return None


def fetch_ticker_info(sym: str, retries: int = 3, delay: float = 2.0):
    """
    Fetch a yfinance Ticker plus a rich ``info`` dict for *sym* using
    the crumb-based Yahoo Finance v10/quoteSummary API.

    Strategy
    --------
    1. Create a curl_cffi chrome124 session.
    2. Warm the session (cookies) and obtain a crumb token.
    3. Fetch v10/quoteSummary with all useful modules.
    4. Build an ``info`` dict compatible with the rest of the codebase.
    5. Return (ticker, info, session) — the same session is passed to
       ``yf.Ticker`` so subsequent ``.financials`` / ``.cashflow`` /
       ``.balance_sheet`` calls reuse the authenticated cookies.

    Raises
    ------
    Exception  if all retries fail or the response contains fewer than
               5 meaningful keys (Yahoo rate-limit sentinel).
    """
    MODULES = (
        "financialData,defaultKeyStatistics,"
        "incomeStatementHistory,cashflowStatementHistory,"
        "balanceSheetHistory,summaryDetail,price,assetProfile"
    )

    for attempt in range(retries):
        try:
            session = _make_session()
            crumb = _get_crumb(session)
            if not crumb:
                raise Exception("Could not obtain crumb")

            url = (
                f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
                f"?modules={MODULES}&crumb={crumb}"
            )
            resp = session.get(url, timeout=20)

            if resp.status_code == 401:
                raise Exception("Yahoo Finance returned 401 (invalid crumb/cookies)")
            if resp.status_code == 429:
                raise Exception("Too Many Requests")
            if resp.status_code != 200:
                raise Exception(f"quoteSummary returned HTTP {resp.status_code}")

            result = resp.json().get("quoteSummary", {}).get("result") or []
            if not result:
                error = resp.json().get("quoteSummary", {}).get("error") or {}
                raise Exception(f"quoteSummary error: {error}")

            raw = result[0]

            def _raw(section: dict, key: str):
                v = section.get(key)
                if isinstance(v, dict):
                    return v.get("raw")
                return v

            fd  = raw.get("financialData",       {})
            dk  = raw.get("defaultKeyStatistics", {})
            sd  = raw.get("summaryDetail",        {})
            pr  = raw.get("price",                {})
            ap  = raw.get("assetProfile",         {})

            info = {
                # Price / market data
                "currentPrice":            _raw(fd,  "currentPrice"),
                "regularMarketPrice":      _raw(pr,  "regularMarketPrice"),
                "marketCap":               _raw(pr,  "marketCap"),
                "currency":                pr.get("currency") or fd.get("financialCurrency"),
                # Company identity
                "longName":                pr.get("longName"),
                "shortName":               pr.get("shortName"),
                "sector":                  ap.get("sector"),
                "industry":                ap.get("industry"),
                "website":                 ap.get("website"),
                "longBusinessSummary":     ap.get("longBusinessSummary"),
                # Share data
                "sharesOutstanding":       _raw(dk,  "sharesOutstanding"),
                "impliedSharesOutstanding":_raw(dk,  "impliedSharesOutstanding"),
                "floatShares":             _raw(dk,  "floatShares"),
                "bookValue":               _raw(dk,  "bookValue"),
                # Valuation ratios
                "trailingPE":              _raw(sd,  "trailingPE"),
                "forwardPE":               _raw(dk,  "forwardPE"),
                "priceToBook":             _raw(dk,  "priceToBook"),
                "priceToSalesTrailing12Months": _raw(sd, "priceToSalesTrailing12Months"),
                "enterpriseToEbitda":      _raw(dk,  "enterpriseToEbitda"),
                "enterpriseToRevenue":     _raw(dk,  "enterpriseToRevenue"),
                "enterpriseValue":         _raw(dk,  "enterpriseValue"),
                "beta":                    _raw(dk,  "beta"),
                # Profitability (pre-computed by Yahoo)
                "grossMargins":            _raw(fd,  "grossMargins"),
                "operatingMargins":        _raw(fd,  "operatingMargins"),
                "profitMargins":           _raw(fd,  "profitMargins"),
                "ebitdaMargins":           _raw(fd,  "ebitdaMargins"),
                "returnOnEquity":          _raw(fd,  "returnOnEquity"),
                "returnOnAssets":          _raw(fd,  "returnOnAssets"),
                # Cash flow
                "freeCashflow":            _raw(fd,  "freeCashflow"),
                "operatingCashflow":       _raw(fd,  "operatingCashflow"),
                # Balance sheet
                "totalDebt":               _raw(fd,  "totalDebt"),
                "totalCash":               _raw(fd,  "totalCash"),
                "debtToEquity":            _raw(fd,  "debtToEquity"),
                "currentRatio":            _raw(fd,  "currentRatio"),
                "quickRatio":              _raw(fd,  "quickRatio"),
                # Revenue / EBITDA
                "totalRevenue":            _raw(fd,  "totalRevenue"),
                "ebitda":                  _raw(fd,  "ebitda"),
                "grossProfits":            _raw(fd,  "grossProfits"),
                # Dividend
                "dividendYield":           _raw(sd,  "dividendYield"),
                "payoutRatio":             _raw(sd,  "payoutRatio"),
                # Equity book value (used in WACC)
                "totalStockholderEquity":  None,  # filled below if possible
            }

            # Compute totalStockholderEquity from bookValue * sharesOutstanding if missing
            bv = info.get("bookValue")
            sh = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if bv and sh:
                info["totalStockholderEquity"] = bv * sh

            if len([v for v in info.values() if v is not None]) < 5:
                raise Exception("Too few fields — likely rate-limited or bad ticker")

            # Build a yf.Ticker using the same warmed session so subsequent
            # .financials / .cashflow / .balance_sheet calls reuse cookies.
            ticker_obj = yf.Ticker(sym, session=session)

            return ticker_obj, info

        except Exception as e:
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                logger.warning(
                    "fetch_ticker_info failed for %s, retrying in %.1fs (%d/%d): %s",
                    sym, wait, attempt + 1, retries, e,
                )
                time.sleep(wait)
            else:
                raise
    raise Exception(f"fetch_ticker_info failed for {sym} after {retries} attempts")


def _cffi_session():
    return cffi_requests.Session(impersonate="chrome124")


def fetch_price_history(ticker: str, period: str = None, interval: str = None) -> pd.DataFrame:
    """
    Fetch OHLCV data for a ticker via yfinance using curl_cffi to bypass rate limits.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume.
    Raises ValueError if the ticker is invalid or no data returned.
    """
    period = period or Config.DEFAULT_PERIOD
    interval = interval or Config.DEFAULT_INTERVAL

    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True, session=_cffi_session())

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
