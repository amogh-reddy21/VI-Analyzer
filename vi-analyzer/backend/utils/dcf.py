"""
utils/dcf.py
DCF-based intrinsic value estimation with bear / base / bull scenarios.

Two-stage growth model:
  Stage 1 (years 1-5): project at the user-supplied growth rate `g`
  Stage 2 (years 6-10): linearly fade g -> terminal_growth
  Terminal value: Gordon Growth at year 10

Raises ValueError when FCF is unavailable or non-positive (DCF is not
meaningful without positive free cash flow).
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

# ── WACC constants ────────────────────────────────────────────────────────────
# Used for auto-computing WACC when the caller doesn't supply scenario overrides.
# Rf: 10-year US Treasury yield (approximate long-run average)
# ERP: Equity risk premium (Damodaran long-run estimate)
# Rd: Cost of debt — approximated from interest_expense / total_debt.
#     Falls back to RF + 1% spread if statement data is unavailable.
# TAX_RATE: US statutory corporate rate (same as metrics.py)
_RF       = 0.045
_ERP      = 0.055
_TAX_RATE = 0.21


def compute_wacc(beta: float, debt: float, equity: float,
                 interest_exp: float, tax_rate: float = _TAX_RATE) -> float | None:
    """
    Full WACC = (E/V) × Re + (D/V) × Rd × (1 - T)

    Re = Rf + β × ERP  (CAPM)
    Rd = interest_expense / total_debt  (approximated from financials)
         falls back to Rf + 1% spread if data unavailable.

    Returns WACC as a decimal (e.g. 0.09) or None if inputs are missing.
    """
    if beta is None or equity is None:
        return None
    v = (equity or 0) + (debt or 0)
    if v <= 0:
        return None
    re = _RF + beta * _ERP
    if debt and debt > 0 and interest_exp and interest_exp > 0:
        rd = interest_exp / debt
    else:
        rd = _RF + 0.01   # fallback: risk-free + 100 bps credit spread
    e_weight = equity / v
    d_weight = (debt or 0) / v
    return round(e_weight * re + d_weight * rd * (1 - tax_rate), 4)


def _safe(val, decimals=2):
    try:
        v = float(val)
        return None if (v != v) else round(v, decimals)
    except (TypeError, ValueError):
        return None


def _two_stage_rates(g, tg, years=10, fade_start=5):
    """
    Return a list of `years` per-year growth rates.
    Years 1..fade_start use `g` flat.
    Years (fade_start+1)..years linearly interpolate g -> tg.

    Example: g=0.15, tg=0.03, years=10, fade_start=5
      -> [0.15, 0.15, 0.15, 0.15, 0.15, 0.126, 0.102, 0.078, 0.054, 0.03]
    """
    rates = []
    fade_years = years - fade_start
    for yr in range(1, years + 1):
        if yr <= fade_start:
            rates.append(g)
        else:
            # linear interpolation from g to tg over fade_years steps
            step = (yr - fade_start)
            rate = g + (tg - g) * step / fade_years
            rates.append(rate)
    return rates


def compute_dcf(ticker_sym: str, scenarios: dict = None) -> dict:
    """
    Compute intrinsic value per share under three growth scenarios.

    Default scenarios (growth_rate, terminal_growth, wacc):
      bear: (0.05, 0.02, 0.10)
      base: (0.10, 0.03, 0.09)
      bull: (0.18, 0.04, 0.08)

    Uses a two-stage model: flat growth for years 1-5, linear fade
    to terminal_growth over years 6-10, then Gordon Growth terminal value.

    Raises ValueError if FCF is unavailable, negative, or zero.
    """
    PROJECTION_YEARS = 10
    FADE_START       = 5

    if scenarios is None:
        scenarios = {
            "bear": {"growth_rate": 0.05, "terminal_growth": 0.02, "wacc": 0.10},
            "base": {"growth_rate": 0.10, "terminal_growth": 0.03, "wacc": 0.09},
            "bull": {"growth_rate": 0.18, "terminal_growth": 0.04, "wacc": 0.08},
        }

    t, info = _yf_ticker_with_retry(ticker_sym)

    # ── Pull trailing FCF ────────────────────────────────────────────────────
    base_fcf = _safe(info.get("freeCashflow"))

    # Fallback: compute from cash flow statement
    if base_fcf is None or base_fcf <= 0:
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                op_keys  = ["Operating Cash Flow",
                            "Cash Flow From Continuing Operating Activities"]
                cap_keys = ["Capital Expenditure"]
                op_cf, cap = None, None
                for k in op_keys:
                    if k in cf.index:
                        op_cf = float(cf.loc[k].iloc[0])
                        break
                for k in cap_keys:
                    if k in cf.index:
                        cap = float(cf.loc[k].iloc[0])
                        break
                if op_cf is not None:
                    base_fcf = op_cf + (cap or 0)
        except Exception as e:
            logger.warning("DCF cashflow fallback failed for %s: %s", ticker_sym, e)

    if base_fcf is None:
        raise ValueError(
            f"Cannot compute DCF for '{ticker_sym}': no free cash flow data available."
        )
    if base_fcf <= 0:
        raise ValueError(
            f"DCF not applicable for '{ticker_sym}': trailing FCF is "
            f"${base_fcf:,.0f} (negative/zero). DCF requires positive FCF. "
            "Consider EV/EBITDA or P/S multiples instead."
        )

    shares = _safe(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    price  = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))

    # Auto-compute WACC from balance sheet for transparency in the response.
    # This is returned as metadata; scenario WACCs can still be caller-overridden.
    _beta   = _safe(info.get("beta"))
    _eq     = _safe(info.get("bookValue") and info.get("sharesOutstanding") and
                    info.get("bookValue") * info.get("sharesOutstanding")) or               _safe(info.get("totalStockholderEquity"))
    _debt   = _safe(info.get("totalDebt"))
    _int    = None
    try:
        cf2 = t.financials
        if cf2 is not None and not cf2.empty:
            for _k in ["Interest Expense", "Interest Expense Non Operating"]:
                if _k in cf2.index:
                    _int = abs(float(cf2.loc[_k].iloc[0]))
                    break
    except Exception:
        pass
    wacc_auto = compute_wacc(_beta, _debt, _eq, _int)

    if not shares or shares <= 0:
        raise ValueError(
            f"Cannot compute DCF for '{ticker_sym}': shares outstanding unavailable."
        )

    results = {}

    for name, params in scenarios.items():
        g   = params["growth_rate"]
        tg  = params["terminal_growth"]
        wc  = params["wacc"]

        if wc <= tg:
            results[name] = {"error": "WACC must exceed terminal growth rate"}
            continue

        # Two-stage: flat g for years 1-5, fade to tg over years 6-10
        per_year_rates = _two_stage_rates(g, tg, PROJECTION_YEARS, FADE_START)

        projected = []
        fcf = base_fcf
        for yr, yr_rate in enumerate(per_year_rates, start=1):
            fcf = fcf * (1 + yr_rate)
            pv  = fcf / ((1 + wc) ** yr)
            projected.append({
                "year":      yr,
                "rate":      round(yr_rate, 4),
                "fcf":       round(fcf, 0),
                "pv":        round(pv,  0),
            })

        # Terminal value (Gordon Growth at year 10)
        terminal_fcf = projected[-1]["fcf"] * (1 + tg)
        terminal_val = terminal_fcf / (wc - tg)
        terminal_pv  = terminal_val / ((1 + wc) ** PROJECTION_YEARS)

        total_pv  = sum(p["pv"] for p in projected) + terminal_pv
        intrinsic = total_pv / shares

        mos = None
        if price and price > 0:
            mos = round((intrinsic - price) / intrinsic * 100, 2)

        results[name] = {
            "growth_rate":        g,
            "terminal_growth":    tg,
            "wacc":               wc,
            "growth_fade":        f"Y{FADE_START+1}–{PROJECTION_YEARS}",
            "base_fcf":           round(base_fcf, 0),
            "projected_fcf":      projected,
            "terminal_value":     round(terminal_val, 0),
            "terminal_pv":        round(terminal_pv, 0),
            "total_pv":           round(total_pv, 0),
            "shares_outstanding": round(shares, 0),
            "intrinsic_value":    round(intrinsic, 2),
            "current_price":      price,
            "margin_of_safety":   mos,
        }

    return {
        "ticker":        ticker_sym.upper(),
        "current_price": price,
        "wacc_auto":     wacc_auto,   # Full WACC from CAPM + D/V×Rd×(1-T); None if data missing
        "scenarios":     results,
        "verdict":       _mos_verdict(results.get("base", {}).get("margin_of_safety")),
    }


def _mos_verdict(mos):
    if mos is None:
        return "unknown"
    if mos >= 30:
        return "strong_buy"
    if mos >= 10:
        return "buy"
    if mos >= -10:
        return "fair_value"
    if mos >= -30:
        return "overvalued"
    return "significantly_overvalued"
