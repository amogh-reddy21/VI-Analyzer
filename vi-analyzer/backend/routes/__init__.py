from flask import Blueprint, jsonify, request
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
import logging

from utils import fetch_price_history, compute_historical_volatility, compute_price_summary
from utils.metrics import fetch_fundamentals
from utils.dcf import compute_dcf

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}
_TICKER_RE    = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")   # e.g. AAPL, BRK.B, BF-B


def _validate_ticker(sym: str):
    """Return (normalised_sym, None) or (None, error_response_tuple)."""
    sym = sym.upper().strip()
    if not _TICKER_RE.match(sym):
        return None, (jsonify({"error": f"Invalid ticker symbol \'{sym}\'. Expected 1-6 uppercase letters (e.g. AAPL, BRK.B)."}), 400)
    return sym, None


# ── Simple in-process TTL cache (5-minute expiry) ────────────────────────────
# NOTE: This cache is per-process and non-persistent. In a multi-worker
# deployment (e.g. gunicorn -w 4) each worker has its own cache. Use Redis
# or Memcached for a shared cache in production.
_cache: dict = {}
_CACHE_TTL = 300  # seconds


def _cache_get(key):
    """Return cached value if it exists and hasn't expired, else None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    value, ts = entry
    if time.time() - ts > _CACHE_TTL:
        del _cache[key]
        return None
    return value


def _cache_set(key, value):
    _cache[key] = (value, time.time())


# ── Health ───────────────────────────────────────────────────────────────────

@api.route("/health")
def health():
    return jsonify({"status": "ok"})


# ── Volatility (existing) ────────────────────────────────────────────────────

@api.route("/stock/<ticker>/volatility")
def get_volatility(ticker: str):
    ticker, err = _validate_ticker(ticker)
    if err: return err
    period = request.args.get("period", "1y")
    window = request.args.get("window", 21, type=int)
    if period not in VALID_PERIODS:
        return jsonify({"error": f"Invalid period '{period}'."}), 400
    if not (5 <= window <= 252):
        return jsonify({"error": "window must be 5-252"}), 400
    try:
        df = fetch_price_history(ticker, period=period)
        hv = compute_historical_volatility(df, window=window)
        return jsonify({"ticker": ticker, "period": period, **hv})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "Fetch failed", "detail": str(e)}), 500


@api.route("/stock/<ticker>/summary")
def get_summary(ticker: str):
    ticker, err = _validate_ticker(ticker)
    if err: return err
    period = request.args.get("period", "1y")
    window = request.args.get("window", 21, type=int)
    try:
        df      = fetch_price_history(ticker, period=period)
        hv      = compute_historical_volatility(df, window=window)
        summary = compute_price_summary(df)
        return jsonify({"ticker": ticker, "period": period, **summary, **hv})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "Fetch failed", "detail": str(e)}), 500


@api.route("/compare")
def compare_volatility():
    tickers_raw = request.args.get("tickers", "")
    period      = request.args.get("period", "1y")
    window      = request.args.get("window", 21, type=int)
    tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "Provide at least one ticker"}), 400
    if len(tickers) > 10:
        return jsonify({"error": "Max 10 tickers"}), 400
    invalid = [t for t in tickers if not _TICKER_RE.match(t)]
    if invalid:
        return jsonify({"error": f"Invalid ticker symbol(s): {', '.join(invalid)}"}), 400
    out = {}
    for sym in tickers:
        try:
            df = fetch_price_history(sym, period=period)
            hv = compute_historical_volatility(df, window=window)
            out[sym] = {"current_hv": hv["current_hv"], "mean_hv": hv["mean_hv"],
                        "min_hv": hv["min_hv"], "max_hv": hv["max_hv"]}
        except Exception as e:
            out[sym] = {"error": str(e)}
    return jsonify(out)


# ── Fundamentals ─────────────────────────────────────────────────────────────

@api.route("/stock/<ticker>/fundamentals")
def get_fundamentals(ticker: str):
    """
    GET /api/stock/<ticker>/fundamentals

    Returns 15+ metrics, scorecard grades, and 10-year financial trends.
    Results are cached for 5 minutes.
    """
    ticker, err = _validate_ticker(ticker)
    if err: return err
    cache_key = f"fundamentals:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit: %s", cache_key)
        return jsonify(cached)
    try:
        data = fetch_fundamentals(ticker)
        _cache_set(cache_key, data)
        return jsonify(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "Failed to fetch fundamentals", "detail": str(e)}), 500


# ── DCF Valuation ─────────────────────────────────────────────────────────────

@api.route("/stock/<ticker>/dcf")
def get_dcf(ticker: str):
    """
    GET /api/stock/<ticker>/dcf
    Optional query params to override defaults:
      bear_g, base_g, bull_g        -- FCF growth rates (e.g. 0.05)
      bear_tg, base_tg, bull_tg     -- terminal growth rates
      bear_wacc, base_wacc, bull_wacc

    Returns bear/base/bull intrinsic values + margin of safety.
    Results are cached for 5 minutes (custom scenario params bypass cache).
    """
    ticker, err = _validate_ticker(ticker)
    if err: return err

    def fp(key, default):
        val = request.args.get(key, type=float)
        return val if val is not None else default

    # ── Sector-aware scenario defaults ──────────────────────────────────────
    # Applying 18% bull growth to a utility is as wrong as 4% to a SaaS company.
    # We pull the sector from yfinance info (fast, already cached by fundamentals)
    # and map it to reasonable starting assumptions. The caller can still override
    # any individual param via query string.
    _SECTOR_DCF_PRESETS = {
        # bucket:  (bear_g, base_g, bull_g, bear_tg, base_tg, bull_tg, base_wacc)
        "tech":     (0.07, 0.13, 0.22, 0.03, 0.04, 0.05, 0.09),
        "financial":(0.04, 0.08, 0.13, 0.02, 0.03, 0.04, 0.10),
        "capital":  (0.02, 0.05, 0.09, 0.01, 0.02, 0.03, 0.08),
        "consumer": (0.03, 0.07, 0.12, 0.02, 0.03, 0.04, 0.08),
        "default":  (0.05, 0.10, 0.18, 0.02, 0.03, 0.04, 0.09),
    }
    from utils.metrics import _get_bucket as _sector_bucket
    try:
        import yfinance as _yf
        _info = _yf.Ticker(ticker).info or {}
        _bucket = _sector_bucket(_info.get("sector"))
    except Exception:
        _bucket = "default"
    _p = _SECTOR_DCF_PRESETS[_bucket]
    _bear_g_d, _base_g_d, _bull_g_d  = _p[0], _p[1], _p[2]
    _bear_tg_d, _base_tg_d, _bull_tg_d = _p[3], _p[4], _p[5]
    _base_wacc_d = _p[6]

    scenarios = {
        "bear": {
            "growth_rate":     fp("bear_g",    _bear_g_d),
            "terminal_growth": fp("bear_tg",   _bear_tg_d),
            "wacc":            fp("bear_wacc", _base_wacc_d + 0.01),
        },
        "base": {
            "growth_rate":     fp("base_g",    _base_g_d),
            "terminal_growth": fp("base_tg",   _base_tg_d),
            "wacc":            fp("base_wacc", _base_wacc_d),
        },
        "bull": {
            "growth_rate":     fp("bull_g",    _bull_g_d),
            "terminal_growth": fp("bull_tg",   _bull_tg_d),
            "wacc":            fp("bull_wacc", max(_base_wacc_d - 0.01, 0.04)),
        },
    }
    # Surface the resolved bucket so the frontend can annotate the UI
    _scenario_bucket = _bucket

    # Only cache if using default scenario params (no query overrides)
    using_defaults = not any(request.args.get(k) for k in [
        "bear_g", "base_g", "bull_g", "bear_tg", "base_tg", "bull_tg",
        "bear_wacc", "base_wacc", "bull_wacc",
    ])
    cache_key = f"dcf:{ticker}" if using_defaults else None
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit: %s", cache_key)
            return jsonify(cached)

    try:
        result = compute_dcf(ticker, scenarios=scenarios)
        if cache_key:
            _cache_set(cache_key, result)
        result["sector_bucket"] = _scenario_bucket
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": "DCF computation failed", "detail": str(e)}), 500


# ── Peer Comparison ───────────────────────────────────────────────────────────

@api.route("/peers")
def compare_peers():
    """
    GET /api/peers?tickers=AAPL,MSFT,GOOGL

    Run fundamentals scorecard across all given tickers for side-by-side comparison.
    Max 8 tickers. Fetches all tickers concurrently to minimise latency.
    Results are cached per-ticker for 5 minutes.
    """
    tickers_raw = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "Provide tickers via ?tickers=AAPL,MSFT"}), 400
    if len(tickers) > 8:
        return jsonify({"error": "Max 8 tickers for peer comparison"}), 400
    invalid = [t for t in tickers if not _TICKER_RE.match(t)]
    if invalid:
        return jsonify({"error": f"Invalid ticker symbol(s): {', '.join(invalid)}"}), 400

    def fetch_one(sym):
        cache_key = f"peers:{sym}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return sym, cached
        data = fetch_fundamentals(sym)
        result = {
            "company":   data["company"],
            "metrics":   data["metrics"],
            "scorecard": data["scorecard"],
        }
        _cache_set(cache_key, result)
        return sym, result

    out = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as executor:
        futures = {executor.submit(fetch_one, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                sym, result = future.result()
                out[sym] = result
            except Exception as e:
                logger.warning("Peer fetch failed for %s: %s", sym, e)
                out[sym] = {"error": str(e)}

    return jsonify(out)
