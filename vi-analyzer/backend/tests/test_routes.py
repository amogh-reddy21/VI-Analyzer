"""
tests/test_routes.py
Unit tests for routes/__init__.py — ticker validation, cache, and HTTP semantics.
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.get_json() == {"status": "ok"}


# ── Ticker validation ─────────────────────────────────────────────────────────

class TestTickerValidation:
    """All ticker-bearing endpoints must reject invalid symbols with 400."""

    INVALID_CASES = [
        "",            # empty (will 404 at routing level, but test valid inputs)
        "TOOLONGXXXX", # > 6 chars
        "123ABC",      # starts with digit
        "A B",         # space
        "AAPL;DROP",   # injection attempt
    ]

    @pytest.mark.parametrize("bad_ticker", ["TOOLONGXXXX", "123ABC", "A B", "AAPL;DROP"])
    def test_volatility_rejects_invalid_ticker(self, client, bad_ticker):
        res = client.get(f"/api/stock/{bad_ticker}/volatility")
        assert res.status_code == 400
        assert "error" in res.get_json()

    @pytest.mark.parametrize("bad_ticker", ["TOOLONGXXXX", "123ABC", "A B", "AAPL;DROP"])
    def test_fundamentals_rejects_invalid_ticker(self, client, bad_ticker):
        res = client.get(f"/api/stock/{bad_ticker}/fundamentals")
        assert res.status_code == 400

    @pytest.mark.parametrize("bad_ticker", ["TOOLONGXXXX", "123ABC", "A B", "AAPL;DROP"])
    def test_dcf_rejects_invalid_ticker(self, client, bad_ticker):
        res = client.get(f"/api/stock/{bad_ticker}/dcf")
        assert res.status_code == 400

    @pytest.mark.parametrize("good_ticker", ["AAPL", "BRK.B", "BF-B", "MSFT"])
    def test_valid_tickers_pass_validation(self, client, good_ticker):
        """Valid tickers should not get a 400 from validation (may 404/500 from yfinance)."""
        with patch("routes.fetch_price_history") as mock_hist:
            mock_hist.side_effect = ValueError("no data")
            res = client.get(f"/api/stock/{good_ticker}/volatility")
            # Must be 404 (yfinance said no data), not 400 (bad ticker format)
            assert res.status_code == 404


# ── Period validation ─────────────────────────────────────────────────────────

class TestPeriodValidation:
    def test_invalid_period_returns_400(self, client):
        res = client.get("/api/stock/AAPL/volatility?period=99y")
        assert res.status_code == 400
        assert "period" in res.get_json().get("error", "").lower()

    def test_valid_periods_pass(self, client):
        with patch("routes.fetch_price_history") as mock_hist:
            mock_hist.side_effect = ValueError("no data")
            for period in ["1mo", "3mo", "6mo", "1y", "2y", "5y"]:
                res = client.get(f"/api/stock/AAPL/volatility?period={period}")
                assert res.status_code == 404  # not 400


# ── DCF — negative FCF returns 422 ───────────────────────────────────────────

class TestDcfNegativeFcf:
    def test_negative_fcf_returns_422(self, client):
        with patch("routes.compute_dcf") as mock_dcf:
            mock_dcf.side_effect = ValueError("FCF is negative/zero")
            res = client.get("/api/stock/AAPL/dcf")
            assert res.status_code == 422
            body = res.get_json()
            assert "error" in body


# ── TTL cache ─────────────────────────────────────────────────────────────────

class TestTtlCache:
    def test_cache_returns_same_result_on_second_call(self, client):
        call_count = {"n": 0}

        def fake_fundamentals(sym):
            call_count["n"] += 1
            return {
                "ticker": sym,
                "company": {"name": "Fake", "sector": None, "industry": None,
                            "market_cap": 1e12, "price": 100.0, "beta": 1.0,
                            "currency": "USD", "website": None, "description": ""},
                "metrics": {}, "scorecard": {},
                "income_trend": {}, "cashflow_trend": {}, "balance_trend": {},
            }

        # Clear the module-level cache before testing
        import routes
        routes._cache.clear()

        with patch("routes.fetch_fundamentals", side_effect=fake_fundamentals):
            res1 = client.get("/api/stock/TSTT/fundamentals")  # TSTT unlikely to be cached
            res2 = client.get("/api/stock/TSTT/fundamentals")

        assert res1.status_code == 200
        assert res2.status_code == 200
        # yfinance called only once; second call served from cache
        assert call_count["n"] == 1, (
            f"Expected 1 upstream call (cache hit on second), got {call_count['n']}"
        )

    def test_cache_expires_after_ttl(self, client):
        """After manually expiring a cache entry, the next call should fetch again."""
        import time
        import routes
        routes._cache.clear()

        call_count = {"n": 0}
        def fake_fundamentals(sym):
            call_count["n"] += 1
            return {
                "ticker": sym,
                "company": {"name": "X", "sector": None, "industry": None,
                            "market_cap": 1e9, "price": 50.0, "beta": 0.8,
                            "currency": "USD", "website": None, "description": ""},
                "metrics": {}, "scorecard": {},
                "income_trend": {}, "cashflow_trend": {}, "balance_trend": {},
            }

        with patch("routes.fetch_fundamentals", side_effect=fake_fundamentals):
            client.get("/api/stock/XYZQ/fundamentals")
            # Manually expire the cache entry
            if "fundamentals:XYZQ" in routes._cache:
                val, _ = routes._cache["fundamentals:XYZQ"]
                routes._cache["fundamentals:XYZQ"] = (val, time.time() - routes._CACHE_TTL - 1)
            client.get("/api/stock/XYZQ/fundamentals")

        assert call_count["n"] == 2, (
            f"Expected 2 upstream calls after TTL expiry, got {call_count['n']}"
        )

# ── /compare ticker validation ────────────────────────────────────────────────

class TestCompareValidation:
    @pytest.mark.parametrize("bad", ["123BAD", "TOOLONGXXXX", "A B", "AAPL;DROP"])
    def test_compare_rejects_invalid_ticker(self, client, bad):
        res = client.get(f"/api/compare?tickers=AAPL,{bad}")
        assert res.status_code == 400
        assert "Invalid" in res.get_json().get("error", "")

    def test_compare_accepts_valid_tickers(self, client):
        """Valid tickers should pass validation (may 404/500 on actual fetch — not 400)."""
        with patch("routes.fetch_price_history", side_effect=ValueError("no data")):
            res = client.get("/api/compare?tickers=AAPL,MSFT")
        # compare returns 200 with per-ticker errors, not a top-level 400
        assert res.status_code == 200


# ── /peers ticker validation ──────────────────────────────────────────────────

class TestPeersValidation:
    @pytest.mark.parametrize("bad", ["123BAD", "TOOLONGXXXX", "A B", "AAPL;DROP"])
    def test_peers_rejects_invalid_ticker(self, client, bad):
        res = client.get(f"/api/peers?tickers=AAPL,{bad}")
        assert res.status_code == 400
        assert "Invalid" in res.get_json().get("error", "")

    def test_peers_accepts_valid_tickers(self, client):
        """Valid tickers should not be rejected with 400."""
        mock_result = {
            "company": {"name": "X", "sector": "Technology", "industry": "Software",
                        "market_cap": 1e9, "price": 50.0, "beta": 1.0,
                        "currency": "USD", "website": None, "description": ""},
            "metrics": {}, "scorecard": {},
            "income_trend": {}, "cashflow_trend": {}, "balance_trend": {},
        }
        with patch("routes.fetch_fundamentals", return_value={**mock_result, "ticker": "AAPL"}):
            res = client.get("/api/peers?tickers=AAPL,MSFT")
        assert res.status_code != 400
