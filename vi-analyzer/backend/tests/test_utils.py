"""
tests/test_utils.py
Unit tests for utils/__init__.py — HV computation and price summary.
No network calls: yfinance.download is mocked throughout.
"""
import math
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from datetime import date, timedelta

from utils import compute_historical_volatility, compute_price_summary, fetch_price_history


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(closes, with_volume=True):
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    dates = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    df = pd.DataFrame({"Close": closes}, index=dates)
    if with_volume:
        df["Volume"] = 1_000_000
    return df


# ── compute_historical_volatility ─────────────────────────────────────────────

class TestComputeHistoricalVolatility:
    def _make_stable(self, n=100):
        """Prices with tiny, consistent growth — very low HV."""
        return _make_df([100.0 * (1.001 ** i) for i in range(n)])

    def test_returns_required_keys(self):
        df = self._make_stable()
        result = compute_historical_volatility(df, window=21)
        for key in ("current_hv", "mean_hv", "min_hv", "max_hv", "window_days", "hv_series"):
            assert key in result, f"Missing key: {key}"

    def test_current_hv_is_non_negative(self):
        """HV is always >= 0; near-zero for stable prices."""
        df = self._make_stable()
        result = compute_historical_volatility(df, window=21)
        assert result["current_hv"] >= 0

    def test_window_days_matches_param(self):
        df = self._make_stable()
        assert compute_historical_volatility(df, window=10)["window_days"] == 10
        assert compute_historical_volatility(df, window=30)["window_days"] == 30

    def test_hv_series_has_correct_length(self):
        df = self._make_stable(n=60)
        result = compute_historical_volatility(df, window=21)
        # rolling std drops first (window) NaNs then .dropna() removes them
        expected_len = 60 - 1 - 21 + 1   # log returns lose 1, rolling loses window-1
        assert len(result["hv_series"]) == expected_len

    def test_hv_series_entries_have_date_and_hv(self):
        df = self._make_stable()
        series = compute_historical_volatility(df, window=21)["hv_series"]
        for entry in series[:3]:
            assert "date" in entry and "hv" in entry
            assert isinstance(entry["hv"], float)

    def test_min_lte_mean_lte_max(self):
        df = self._make_stable()
        r = compute_historical_volatility(df, window=21)
        assert r["min_hv"] <= r["mean_hv"] <= r["max_hv"]

    def test_high_volatility_prices_give_higher_hv(self):
        """A choppy price series should produce higher HV than a smooth one."""
        import random
        random.seed(42)
        smooth = _make_df([100 + i * 0.1 for i in range(100)])
        choppy = _make_df([100 + random.uniform(-5, 5) for _ in range(100)])
        hv_smooth = compute_historical_volatility(smooth, window=10)["mean_hv"]
        hv_choppy = compute_historical_volatility(choppy, window=10)["mean_hv"]
        assert hv_choppy > hv_smooth

    def test_constant_prices_give_zero_or_near_zero_hv(self):
        """Constant prices have zero log returns → zero HV."""
        df = _make_df([100.0] * 60)
        result = compute_historical_volatility(df, window=21)
        assert result["current_hv"] == pytest.approx(0.0, abs=1e-6)


# ── compute_price_summary ─────────────────────────────────────────────────────

class TestComputePriceSummary:
    def _df(self):
        closes = [100.0 + i for i in range(30)]
        return _make_df(closes)

    def test_returns_required_keys(self):
        result = compute_price_summary(self._df())
        for key in ("latest_close", "pct_change_1d", "high_52w", "low_52w",
                    "avg_volume_20d", "price_series"):
            assert key in result

    def test_latest_close_is_last_price(self):
        closes = [100.0 + i for i in range(30)]
        df = _make_df(closes)
        assert compute_price_summary(df)["latest_close"] == pytest.approx(129.0)

    def test_pct_change_formula(self):
        # 128 -> 129: (129-128)/128*100 = 0.78125
        closes = [100.0 + i for i in range(30)]
        result = compute_price_summary(_make_df(closes))
        assert result["pct_change_1d"] == pytest.approx(100 * (129 - 128) / 128, rel=1e-4)

    def test_high_52w_is_max(self):
        closes = [100.0 + i for i in range(30)]
        result = compute_price_summary(_make_df(closes))
        assert result["high_52w"] == pytest.approx(129.0)

    def test_low_52w_is_min(self):
        closes = [100.0 + i for i in range(30)]
        result = compute_price_summary(_make_df(closes))
        assert result["low_52w"] == pytest.approx(100.0)

    def test_avg_volume_present_when_volume_in_df(self):
        result = compute_price_summary(self._df())
        assert result["avg_volume_20d"] == pytest.approx(1_000_000.0)

    def test_avg_volume_none_when_no_volume_column(self):
        df = _make_df([100.0 + i for i in range(30)], with_volume=False)
        result = compute_price_summary(df)
        assert result["avg_volume_20d"] is None

    def test_price_series_entries_have_date_and_close(self):
        result = compute_price_summary(self._df())
        for entry in result["price_series"][:3]:
            assert "date" in entry and "close" in entry

    def test_single_price_pct_change_is_zero(self):
        """Only one price: prev_close == latest_close → 0% change."""
        df = _make_df([150.0])
        result = compute_price_summary(df)
        assert result["pct_change_1d"] == pytest.approx(0.0)


# ── fetch_price_history ───────────────────────────────────────────────────────

class TestFetchPriceHistory:
    def test_raises_on_empty_dataframe(self):
        with patch("utils.yf.download", return_value=pd.DataFrame()):
            with pytest.raises(ValueError, match="No price data"):
                fetch_price_history("FAKE")

    def test_returns_sorted_index(self):
        # Build an unsorted DataFrame to verify sort_index is called
        dates = pd.date_range("2023-01-05", periods=5, freq="B")
        df_unsorted = pd.DataFrame({"Close": [5, 4, 3, 2, 1]}, index=dates[::-1])
        with patch("utils.yf.download", return_value=df_unsorted):
            result = fetch_price_history("AAPL")
        assert result.index.is_monotonic_increasing

    def test_flattens_multiindex_columns(self):
        dates = pd.date_range("2023-01-02", periods=5, freq="B")
        arrays = [["Close", "Open"], ["AAPL", "AAPL"]]
        mi = pd.MultiIndex.from_arrays(arrays)
        df_mi = pd.DataFrame([[100, 99], [101, 100], [102, 101], [103, 102], [104, 103]],
                              index=dates, columns=mi)
        with patch("utils.yf.download", return_value=df_mi):
            result = fetch_price_history("AAPL")
        assert not isinstance(result.columns, pd.MultiIndex)
        assert "Close" in result.columns
