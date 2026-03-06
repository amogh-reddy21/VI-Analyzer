"""
utils/metrics.py
Compute 15+ fundamental metrics from yfinance Ticker objects.
"""
import logging
import time
import yfinance as yf

logger = logging.getLogger(__name__)


def _yf_ticker_with_retry(sym: str, retries: int = 3, delay: float = 2.0):
    """Fetch yfinance Ticker using curl_cffi chrome124 session to bypass rate limits."""
    from curl_cffi import requests as cffi_requests
    for attempt in range(retries):
        try:
            session = cffi_requests.Session(impersonate="chrome124")
            t = yf.Ticker(sym, session=session)
            info = t.info or {}
            if len(info) < 5:
                raise Exception("Too Many Requests")
            return t, info
        except Exception as e:
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                logger.warning("yfinance failed for %s, retrying in %.1fs (%d/%d): %s", sym, wait, attempt+1, retries, e)
                time.sleep(wait)
            else:
                raise
    raise Exception(f"yfinance failed for {sym} after {retries} attempts")

# ── Tax rate used in ROIC: EBIT × (1 - TAX_RATE) / Invested Capital ─────────
# US statutory corporate rate. Override per ticker if jurisdiction is known.
# International tickers (ADRs) may have materially different effective rates.
TAX_RATE = 0.21

# ── Sector-bucketed scorecard thresholds ─────────────────────────────────────
# yfinance sector strings: "Technology", "Healthcare", "Consumer Staples",
# "Consumer Cyclical", "Communication Services", "Industrials", "Energy",
# "Utilities", "Real Estate", "Basic Materials", "Financial Services"
#
# Buckets:
#   "tech"       — Technology, Communication Services, Healthcare
#   "financial"  — Financial Services  (D/E and current_ratio are meaningless for banks)
#   "capital"    — Energy, Utilities, Industrials, Basic Materials, Real Estate
#   "consumer"   — Consumer Staples, Consumer Cyclical
#   "default"    — anything unmapped

_SECTOR_BUCKET = {
    "Technology":               "tech",
    "Communication Services":   "tech",
    "Healthcare":               "tech",
    "Financial Services":       "financial",
    "Energy":                   "capital",
    "Utilities":                "capital",
    "Industrials":              "capital",
    "Basic Materials":          "capital",
    "Real Estate":              "capital",
    "Consumer Staples":         "consumer",
    "Consumer Cyclical":        "consumer",
}

# Each metric tuple: (pass_threshold, warn_threshold).
# grade() interprets direction via higher_is_better. None = skip (grade returns "na").
_THRESHOLDS = {
    "tech": {
        "gross_margin_pct":     (55, 35),
        "operating_margin_pct": (20,  8),
        "net_margin_pct":       (15,  5),
        "fcf_margin_pct":       (15,  8),
        "roe_pct":              (20, 12),
        "roa_pct":              (10,  5),
        "roic_pct":             (15, 10),
        "debt_to_equity":       (1,   2),
        "interest_coverage":    (8,   4),
        "current_ratio":        (1.5, 1.0),
        "pe_ratio":             (30, 50),
        "ev_ebitda":            (20, 30),
        "revenue_cagr_3y":      (0.10, 0.05),
        "fcf_cagr_3y":          (0.10, 0.05),
    },
    "financial": {
        "gross_margin_pct":     (40, 20),
        "operating_margin_pct": (20,  8),
        "net_margin_pct":       (15,  5),
        "fcf_margin_pct":       (10,  5),
        "roe_pct":              (12,  8),
        "roa_pct":              (1,   0.5),
        "roic_pct":             (10,  6),
        "debt_to_equity":       (None, None),   # meaningless for banks
        "interest_coverage":    (None, None),   # banks borrow to lend — skip
        "current_ratio":        (None, None),   # not applicable
        "pe_ratio":             (15, 25),
        "ev_ebitda":            (12, 20),
        "revenue_cagr_3y":      (0.05, 0.02),
        "fcf_cagr_3y":          (0.05, 0.02),
    },
    "capital": {
        "gross_margin_pct":     (30, 15),
        "operating_margin_pct": (10,  4),
        "net_margin_pct":       (7,   2),
        "fcf_margin_pct":       (8,   3),
        "roe_pct":              (12,  7),
        "roa_pct":              (5,   2),
        "roic_pct":             (8,   5),
        "debt_to_equity":       (2,   3),
        "interest_coverage":    (4,   2),
        "current_ratio":        (1.2, 1.0),
        "pe_ratio":             (20, 35),
        "ev_ebitda":            (12, 20),
        "revenue_cagr_3y":      (0.05, 0.02),
        "fcf_cagr_3y":          (0.05, 0.02),
    },
    "consumer": {
        "gross_margin_pct":     (35, 20),
        "operating_margin_pct": (10,  4),
        "net_margin_pct":       (7,   2),
        "fcf_margin_pct":       (8,   3),
        "roe_pct":              (15,  8),
        "roa_pct":              (6,   3),
        "roic_pct":             (10,  6),
        "debt_to_equity":       (1.5, 2.5),
        "interest_coverage":    (5,   3),
        "current_ratio":        (1.3, 1.0),
        "pe_ratio":             (22, 35),
        "ev_ebitda":            (14, 22),
        "revenue_cagr_3y":      (0.06, 0.02),
        "fcf_cagr_3y":          (0.06, 0.02),
    },
    "default": {
        "gross_margin_pct":     (40, 20),
        "operating_margin_pct": (15,  5),
        "net_margin_pct":       (10,  3),
        "fcf_margin_pct":       (10,  5),
        "roe_pct":              (15, 10),
        "roa_pct":              (8,   4),
        "roic_pct":             (12,  8),
        "debt_to_equity":       (1,   2),
        "interest_coverage":    (5,   3),
        "current_ratio":        (1.5, 1.0),
        "pe_ratio":             (25, 40),
        "ev_ebitda":            (15, 25),
        "revenue_cagr_3y":      (0.08, 0.03),
        "fcf_cagr_3y":          (0.08, 0.03),
    },
}


def _get_bucket(sector: str) -> str:
    """Map a yfinance sector string to a threshold bucket name."""
    return _SECTOR_BUCKET.get(sector or "", "default")


def _safe(val, decimals=4):
    """Return rounded float or None if val is None/NaN."""
    try:
        v = float(val)
        return None if (v != v) else round(v, decimals)  # NaN check
    except (TypeError, ValueError):
        return None


def _cagr(series, years):
    """
    Compound annual growth rate over `years` from a list oldest->newest.

    Returns None if:
      - Fewer than 2 data points after removing None values
      - Any value is <= 0 (loss year or zero revenue — CAGR is not meaningful
        when the series crosses zero or is negative)
    """
    clean = [x for x in series if x is not None]
    if len(clean) < 2:
        return None
    # If any value is zero or negative, CAGR is mathematically undefined / misleading
    if any(x <= 0 for x in clean):
        return None
    start, end = clean[0], clean[-1]
    n = min(len(clean) - 1, years)
    if n <= 0:
        return None
    return round((end / start) ** (1 / n) - 1, 4)


def fetch_fundamentals(ticker_sym: str) -> dict:
    """
    Pull financial statements and compute 15+ fundamental metrics.
    Returns a dict with keys: info, income_trend, balance_trend,
    cashflow_trend, metrics, scorecard.
    """
    t, info = _yf_ticker_with_retry(ticker_sym)

    # ── Raw statements (annual, most-recent first) ──────────────────────────
    try:
        inc = t.financials          # income statement  (rows=metrics, cols=dates)
    except Exception as e:
        logger.warning("Could not fetch income statement for %s: %s", ticker_sym, e)
        inc = None
    try:
        bal = t.balance_sheet
    except Exception as e:
        logger.warning("Could not fetch balance sheet for %s: %s", ticker_sym, e)
        bal = None
    try:
        cf = t.cashflow
    except Exception as e:
        logger.warning("Could not fetch cash flow statement for %s: %s", ticker_sym, e)
        cf = None

    def row(stmt, *keys):
        """Try multiple key names, return list oldest->newest (up to 10 yrs)."""
        if stmt is None:
            return []
        for key in keys:
            if key in stmt.index:
                vals = stmt.loc[key].dropna()
                return [_safe(v) for v in reversed(vals.tolist())]
        return []

    # ── Build time-series ────────────────────────────────────────────────────
    revenue      = row(inc,  "Total Revenue")
    net_income   = row(inc,  "Net Income")
    ebit         = row(inc,  "EBIT", "Operating Income")
    interest_exp = row(inc,  "Interest Expense")
    gross_profit = row(inc,  "Gross Profit")
    ebitda       = row(inc,  "EBITDA", "Normalized EBITDA")

    total_assets   = row(bal, "Total Assets")
    total_equity   = row(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    total_debt     = row(bal, "Total Debt", "Long Term Debt And Capital Lease Obligation")
    current_assets = row(bal, "Current Assets")
    current_liab   = row(bal, "Current Liabilities")

    op_cf  = row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex  = row(cf, "Capital Expenditure")
    fcf_raw = []
    if op_cf and capex:
        for o, c in zip(op_cf, capex):
            if o is not None and c is not None:
                fcf_raw.append(round(o + c, 0))   # capex is negative in yfinance
            else:
                fcf_raw.append(None)
    elif op_cf:
        fcf_raw = op_cf

    shares = _safe(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    price  = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    market_cap = _safe(info.get("marketCap"))

    # ── Point-in-time metrics (latest available) ─────────────────────────────
    def latest(lst):
        return lst[-1] if lst else None

    rev_l   = latest(revenue)
    ni_l    = latest(net_income)
    ebit_l  = latest(ebit)
    gp_l    = latest(gross_profit)
    fcf_l   = latest(fcf_raw)
    ta_l    = latest(total_assets)
    eq_l    = latest(total_equity)
    debt_l  = latest(total_debt)
    ca_l    = latest(current_assets)
    cl_l    = latest(current_liab)
    eb_l    = latest(ebitda)

    gross_margin   = _safe(gp_l  / rev_l  * 100) if rev_l  and gp_l  else None
    op_margin      = _safe(ebit_l / rev_l * 100) if rev_l  and ebit_l else None
    net_margin     = _safe(ni_l  / rev_l  * 100) if rev_l  and ni_l  else None
    fcf_margin     = _safe(fcf_l / rev_l  * 100) if rev_l  and fcf_l else None
    roe            = _safe(ni_l  / eq_l   * 100) if eq_l   and ni_l  else None
    roa            = _safe(ni_l  / ta_l   * 100) if ta_l   and ni_l  else None
    # ROIC = EBIT(1-t) / (Equity + Debt)
    inv_capital    = (eq_l or 0) + (debt_l or 0)
    roic           = _safe(ebit_l * (1 - TAX_RATE) / inv_capital * 100) if inv_capital and ebit_l else None
    debt_equity    = _safe(debt_l / eq_l) if eq_l and debt_l else None
    interest_cov   = _safe(ebit_l / abs(latest(interest_exp))) if latest(interest_exp) and ebit_l else None
    current_ratio  = _safe(ca_l  / cl_l) if ca_l and cl_l else None
    pe             = _safe(info.get("trailingPE") or info.get("forwardPE"))
    pb             = _safe(info.get("priceToBook"))
    ps             = _safe(info.get("priceToSalesTrailing12Months"))
    pfcf           = _safe(market_cap / fcf_l) if market_cap and fcf_l and fcf_l > 0 else None
    ev_ebitda      = _safe(info.get("enterpriseToEbitda"))

    rev_cagr_3y  = _cagr(revenue[-3:],  3) if len(revenue)  >= 3 else None
    rev_cagr_5y  = _cagr(revenue[-5:],  5) if len(revenue)  >= 5 else None
    fcf_cagr_3y  = _cagr(fcf_raw[-3:], 3) if len(fcf_raw)  >= 3 else None
    ni_cagr_3y   = _cagr(net_income[-3:], 3) if len(net_income) >= 3 else None

    metrics = {
        # Profitability
        "gross_margin_pct":     gross_margin,
        "operating_margin_pct": op_margin,
        "net_margin_pct":       net_margin,
        "fcf_margin_pct":       fcf_margin,
        "roe_pct":              roe,
        "roa_pct":              roa,
        "roic_pct":             roic,
        # Leverage & Liquidity
        "debt_to_equity":       debt_equity,
        "interest_coverage":    interest_cov,
        "current_ratio":        current_ratio,
        # Valuation
        "pe_ratio":             pe,
        "pb_ratio":             pb,
        "ps_ratio":             ps,
        "p_fcf":                pfcf,
        "ev_ebitda":            ev_ebitda,
        # Growth (as decimals, e.g. 0.12 = 12%)
        "revenue_cagr_3y":      rev_cagr_3y,
        "revenue_cagr_5y":      rev_cagr_5y,
        "fcf_cagr_3y":          fcf_cagr_3y,
        "net_income_cagr_3y":   ni_cagr_3y,
    }

    # ── Scorecard: pass/fail/warn per metric ────────────────────────────────
    def grade(val, good, warn_lo=None, warn_hi=None, higher_is_better=True):
        if val is None:
            return "na"
        if higher_is_better:
            if val >= good:
                return "pass"
            if warn_lo is not None and val >= warn_lo:
                return "warn"
            return "fail"
        else:
            if val <= good:
                return "pass"
            if warn_hi is not None and val <= warn_hi:
                return "warn"
            return "fail"

    # Sector-aware thresholds: grading WMT on the same bar as AAPL is misleading.
    bucket = _get_bucket(info.get("sector"))
    th = _THRESHOLDS[bucket]

    def _th(key, higher=True):
        """Look up sector threshold for key; return "na" if thresholds are None."""
        good, warn = th[key]
        if good is None:
            return "na"
        return grade(
            {
                "gross_margin_pct": gross_margin, "operating_margin_pct": op_margin,
                "net_margin_pct": net_margin,     "fcf_margin_pct": fcf_margin,
                "roe_pct": roe,                   "roa_pct": roa,
                "roic_pct": roic,                 "debt_to_equity": debt_equity,
                "interest_coverage": interest_cov,"current_ratio": current_ratio,
                "pe_ratio": pe,                   "ev_ebitda": ev_ebitda,
                "revenue_cagr_3y": rev_cagr_3y,  "fcf_cagr_3y": fcf_cagr_3y,
            }[key],
            good, warn, higher_is_better=higher,
        )

    scorecard = {
        "gross_margin_pct":     _th("gross_margin_pct"),
        "operating_margin_pct": _th("operating_margin_pct"),
        "net_margin_pct":       _th("net_margin_pct"),
        "fcf_margin_pct":       _th("fcf_margin_pct"),
        "roe_pct":              _th("roe_pct"),
        "roa_pct":              _th("roa_pct"),
        "roic_pct":             _th("roic_pct"),
        "debt_to_equity":       _th("debt_to_equity",   higher=False),
        "interest_coverage":    _th("interest_coverage"),
        "current_ratio":        _th("current_ratio"),
        "pe_ratio":             _th("pe_ratio",         higher=False),
        "ev_ebitda":            _th("ev_ebitda",        higher=False),
        "revenue_cagr_3y":      _th("revenue_cagr_3y")  if rev_cagr_3y else "na",
        "fcf_cagr_3y":          _th("fcf_cagr_3y")      if fcf_cagr_3y else "na",
    }
    # Expose the bucket so the frontend can show "Graded vs: tech/consumer/…"
    scorecard["_sector_bucket"] = bucket

    # ── Trend series for charts ──────────────────────────────────────────────
    def zip_dates(stmt, series_vals):
        """
        Return [{year, value}] aligned to statement column dates.
        Truncates to the shorter of the two sequences to prevent misalignment
        when yfinance returns partial data.
        """
        if stmt is None or not series_vals:
            return []
        dates = [str(c.year) for c in reversed(stmt.columns.tolist())]
        n = min(len(dates), len(series_vals))
        return [
            {"year": dates[i], "value": series_vals[i]}
            for i in range(n)
            if series_vals[i] is not None
        ]

    income_trend = {
        "revenue":      zip_dates(inc, revenue),
        "gross_profit": zip_dates(inc, gross_profit),
        "net_income":   zip_dates(inc, net_income),
        "ebitda":       zip_dates(inc, ebitda),
    }
    cashflow_trend = {
        "operating_cf": zip_dates(cf, op_cf),
        "capex":        zip_dates(cf, capex),
        "fcf":          zip_dates(cf, fcf_raw),
    }
    balance_trend = {
        "total_assets": zip_dates(bal, total_assets),
        "total_equity": zip_dates(bal, total_equity),
        "total_debt":   zip_dates(bal, total_debt),
    }

    company_info = {
        "name":        info.get("longName") or info.get("shortName"),
        "sector":      info.get("sector"),
        "industry":    info.get("industry"),
        "market_cap":  market_cap,
        "price":       price,
        "beta":        _safe(info.get("beta")),
        "currency":    info.get("currency", "USD"),
        "website":     info.get("website"),
        "description": (info.get("longBusinessSummary") or "")[:400],
    }

    return {
        "ticker":         ticker_sym.upper(),
        "company":        company_info,
        "metrics":        metrics,
        "scorecard":      scorecard,
        "income_trend":   income_trend,
        "cashflow_trend": cashflow_trend,
        "balance_trend":  balance_trend,
    }
