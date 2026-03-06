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
    Fetch the Yahoo Finance crumb needed for v10/quoteSummary API calls.

    Strategy (in order):
    1. Visit finance.yahoo.com/quote/AAPL/ and extract the crumb from the
       HTML boot JSON — works even when the /v1/test/getcrumb endpoint is
       rate-limited. The HTML contains the crumb both as plain JSON and as
       a backslash-escaped JS string inside a <script> tag.
    2. Fall back to /v1/test/getcrumb if HTML extraction fails.

    Returns the crumb string, or None if all methods fail.
    """
    try:
        r = session.get(
            "https://finance.yahoo.com/quote/AAPL/",
            timeout=20,
            allow_redirects=True,
        )
        if r.status_code == 200:
            html = r.text
            # Pattern A: escaped JS string in <script> tag
            #   \"user\":{\"age\":...\"crumb\":\"XXXXX\"
            m = re.search(r'\\"user\\":\{\\"age\\":[^}]*\\"crumb\\":\\"([^\\]{5,25})\\"', html)
            if m:
                logger.debug("Extracted crumb (escaped JS): %s", m.group(1))
                return m.group(1)
            # Pattern B: plain JSON (unescaped)
            #   "user":{"age":..."crumb":"XXXXX"
            m2 = re.search(r'"user":\{"age":[^}]*"crumb":"([^"]{5,25})"', html)
            if m2:
                logger.debug("Extracted crumb (plain JSON): %s", m2.group(1))
                return m2.group(1)
    except Exception as e:
        logger.warning("_get_crumb HTML extraction failed: %s", e)

    # Fallback: API endpoint (may be rate-limited on shared IPs)
    try:
        rc = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if rc.status_code == 200 and rc.text.strip():
            logger.debug("Got crumb from /v1/test/getcrumb: %s", rc.text.strip())
            return rc.text.strip()
    except Exception as e:
        logger.warning("_get_crumb API fallback failed: %s", e)

    return None

def fetch_ticker_info(sym: str, retries: int = 3, delay: float = 2.0):
    """
    Fetch a yfinance Ticker and build a rich ``info`` dict without relying on
    ``Ticker.info`` (which requires the Yahoo Finance crumb/quoteSummary API
    that is blocked on shared server IPs like Render free tier).

    Data sources (all use the chart/v8 endpoint which is never blocked):
      - ``Ticker.fast_info``      — price, market cap, shares, 52w range
      - ``Ticker.financials``     — income statement (revenue, margins, EBIT…)
      - ``Ticker.cashflow``       — FCF, operating CF, capex
      - ``Ticker.balance_sheet``  — assets, equity, debt, current ratio
      - ``Ticker.info``           — attempted last; if it fails or is sparse
                                    we fill from computed values above

    Returns (ticker_obj, info_dict).
    Raises Exception if price data is completely unavailable.
    """
    for attempt in range(retries):
        try:
            session = _make_session()
            t = yf.Ticker(sym, session=session)

            # ── 1. fast_info (chart endpoint — always works) ─────────────
            fi = t.fast_info
            price      = _sf(fi.last_price)
            market_cap = _sf(fi.market_cap)
            shares     = _sf(fi.shares)
            currency   = getattr(fi, "currency", "USD") or "USD"

            if not price:
                raise Exception(f"No price data for {sym}")

            # ── 2. Financial statements (also use chart endpoint) ─────────
            def _row(stmt, *keys):
                if stmt is None or stmt.empty:
                    return None
                for key in keys:
                    if key in stmt.index:
                        v = stmt.loc[key].iloc[0]
                        try:
                            f = float(v)
                            return None if f != f else f   # NaN guard
                        except (TypeError, ValueError):
                            pass
                return None

            def _col_years(stmt, *keys):
                """Return list oldest→newest (up to 5 yrs) for a row."""
                if stmt is None or stmt.empty:
                    return []
                for key in keys:
                    if key in stmt.index:
                        vals = stmt.loc[key].dropna()
                        return [_sf(v) for v in reversed(vals.tolist())]
                return []

            try:
                fin = t.financials
            except Exception:
                fin = None
            try:
                cf = t.cashflow
            except Exception:
                cf = None
            try:
                bal = t.balance_sheet
            except Exception:
                bal = None

            revenue    = _row(fin, "Total Revenue")
            gross_p    = _row(fin, "Gross Profit")
            ebit       = _row(fin, "EBIT", "Operating Income")
            ebitda     = _row(fin, "EBITDA", "Normalized EBITDA")
            net_inc    = _row(fin, "Net Income")
            int_exp    = _row(fin, "Interest Expense")
            fcf        = _row(cf,  "Free Cash Flow")
            op_cf      = _row(cf,  "Operating Cash Flow",
                               "Cash Flow From Continuing Operating Activities")
            capex      = _row(cf,  "Capital Expenditure")
            tot_assets = _row(bal, "Total Assets")
            tot_equity = _row(bal, "Stockholders Equity", "Common Stock Equity")
            tot_debt   = _row(bal, "Total Debt")
            cur_assets = _row(bal, "Current Assets")
            cur_liab   = _row(bal, "Current Liabilities")

            # Derive FCF if not directly available
            if fcf is None and op_cf is not None and capex is not None:
                fcf = op_cf + capex

            # Compute ratios from statements
            gross_margins   = _sf(gross_p / revenue) if revenue and gross_p else None
            op_margins      = _sf(ebit    / revenue) if revenue and ebit    else None
            profit_margins  = _sf(net_inc / revenue) if revenue and net_inc else None
            ebitda_margins  = _sf(ebitda  / revenue) if revenue and ebitda  else None
            roe             = _sf(net_inc / tot_equity) if tot_equity and net_inc else None
            roa             = _sf(net_inc / tot_assets) if tot_assets and net_inc else None
            debt_to_equity  = _sf(tot_debt / tot_equity * 100) if tot_equity and tot_debt else None
            current_ratio   = _sf(cur_assets / cur_liab) if cur_assets and cur_liab else None
            pe_computed     = _sf(market_cap / net_inc) if market_cap and net_inc and net_inc > 0 else None
            pfcf_computed   = _sf(market_cap / fcf)     if market_cap and fcf and fcf > 0 else None
            ev_computed     = (market_cap or 0) + (tot_debt or 0)
            ev_ebitda_comp  = _sf(ev_computed / ebitda) if ebitda and ebitda > 0 else None
            book_value_ps   = _sf(tot_equity / shares)  if tot_equity and shares else None
            pb_computed     = _sf(price / book_value_ps) if price and book_value_ps else None

            # ── 3. Try Ticker.info for enrichment (beta, PE, sector…) ────
            extra = {}
            try:
                raw_info = t.info or {}
                if len(raw_info) >= 10:
                    extra = raw_info
                    logger.debug("fetch_ticker_info: Ticker.info returned %d keys", len(raw_info))
                else:
                    logger.debug("fetch_ticker_info: Ticker.info too sparse (%d keys), using computed values", len(raw_info))
            except Exception as ie:
                logger.debug("fetch_ticker_info: Ticker.info failed (%s), using computed values", ie)

            # ── 4. Build unified info dict ────────────────────────────────
            def _e(key, fallback=None):
                """Get from extra (Ticker.info) or return fallback."""
                v = extra.get(key)
                return v if v is not None else fallback

            info = {
                # Price / market data
                "currentPrice":             price,
                "regularMarketPrice":       price,
                "marketCap":                market_cap,
                "currency":                 _e("currency", currency),
                # Company identity (only from .info; None if blocked)
                "longName":                 _e("longName") or _e("shortName"),
                "shortName":                _e("shortName"),
                "sector":                   _e("sector"),
                "industry":                 _e("industry"),
                "website":                  _e("website"),
                "longBusinessSummary":      _e("longBusinessSummary"),
                # Shares
                "sharesOutstanding":        shares,
                "impliedSharesOutstanding": shares,
                "floatShares":              _e("floatShares"),
                "bookValue":                book_value_ps,
                # Valuation ratios — prefer .info, fall back to computed
                "trailingPE":               _e("trailingPE", pe_computed),
                "forwardPE":                _e("forwardPE"),
                "priceToBook":              _e("priceToBook", pb_computed),
                "priceToSalesTrailing12Months": _e("priceToSalesTrailing12Months",
                                               _sf(market_cap / revenue) if market_cap and revenue else None),
                "enterpriseToEbitda":       _e("enterpriseToEbitda", ev_ebitda_comp),
                "enterpriseToRevenue":      _e("enterpriseToRevenue",
                                               _sf(ev_computed / revenue) if revenue else None),
                "enterpriseValue":          _e("enterpriseValue", ev_computed),
                "beta":                     _e("beta"),
                # Profitability — prefer .info, fall back to computed from statements
                "grossMargins":             _e("grossMargins",     gross_margins),
                "operatingMargins":         _e("operatingMargins", op_margins),
                "profitMargins":            _e("profitMargins",    profit_margins),
                "ebitdaMargins":            _e("ebitdaMargins",    ebitda_margins),
                "returnOnEquity":           _e("returnOnEquity",   roe),
                "returnOnAssets":           _e("returnOnAssets",   roa),
                # Cash flow
                "freeCashflow":             _e("freeCashflow", fcf),
                "operatingCashflow":        _e("operatingCashflow", op_cf),
                # Balance sheet
                "totalDebt":                _e("totalDebt",  tot_debt),
                "totalCash":                _e("totalCash"),
                "debtToEquity":             _e("debtToEquity", debt_to_equity),
                "currentRatio":             _e("currentRatio", current_ratio),
                "quickRatio":               _e("quickRatio"),
                # Revenue / EBITDA
                "totalRevenue":             _e("totalRevenue", revenue),
                "ebitda":                   _e("ebitda", ebitda),
                "grossProfits":             _e("grossProfits", gross_p),
                # Dividend
                "dividendYield":            _e("dividendYield"),
                "payoutRatio":              _e("payoutRatio"),
                # Equity book value (used in WACC)
                "totalStockholderEquity":   tot_equity,
                # P/FCF
                "p_fcf":                    pfcf_computed,
            }

            logger.info("fetch_ticker_info OK for %s (price=%.2f, FCF=%s, beta=%s)",
                        sym, price, fcf, info.get("beta"))
            return t, info

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


def _sf(val, decimals=4):
    """Safe float — returns None for None/NaN."""
    try:
        v = float(val)
        return None if (v != v) else round(v, decimals)
    except (TypeError, ValueError):
        return None


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
