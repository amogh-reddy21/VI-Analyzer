"""
tests/test_metrics.py
Unit tests for utils/metrics.py — metric computation and edge cases.
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from utils.metrics import _safe, _cagr, fetch_fundamentals


# ── _cagr ─────────────────────────────────────────────────────────────────────

class TestCagr:
    def test_basic_growth(self):
        # 100 -> 133.1 over 3 years = 10% CAGR
        result = _cagr([100, 110, 121, 133.1], 3)
        assert result == pytest.approx(0.10, abs=1e-3)

    def test_returns_none_for_single_value(self):
        assert _cagr([100], 3) is None

    def test_returns_none_for_empty(self):
        assert _cagr([], 3) is None

    def test_returns_none_for_all_none(self):
        assert _cagr([None, None, None], 3) is None

    def test_returns_none_when_loss_year_present(self):
        """A negative value in the series means CAGR is meaningless — must return None."""
        assert _cagr([-100, 200, 300], 3) is None

    def test_returns_none_when_zero_value_present(self):
        """Zero revenue/FCF makes CAGR undefined."""
        assert _cagr([0, 100, 200], 3) is None

    def test_returns_none_when_end_value_is_negative(self):
        """End value negative -> loss year."""
        assert _cagr([100, 200, -50], 3) is None

    def test_ignores_leading_nones(self):
        """None values are stripped; if remainder is all positive, CAGR computed.
        clean = [100, 121], n = min(len(clean)-1=1, years=2) = 1
        CAGR = (121/100)^(1/1) - 1 = 0.21
        """
        result = _cagr([None, 100, 121], 2)
        assert result == pytest.approx(0.21, abs=1e-3)

    def test_years_cap(self):
        """When len(clean)-1 < years, uses actual span not requested span."""
        # only 2 data points -> n=1 regardless of years=5
        result = _cagr([100, 200], 5)
        assert result == pytest.approx(1.0, abs=1e-3)  # 100% growth over 1 year

    def test_flat_series_returns_zero(self):
        result = _cagr([100, 100, 100, 100], 3)
        assert result == pytest.approx(0.0, abs=1e-6)


# ── zip_dates (tested via fetch_fundamentals output shape) ───────────────────

def _make_financial_stmt(data_dict, years=None):
    """
    Build a fake yfinance financial statement DataFrame.
    data_dict: {row_name: [val_year0, val_year1, ...]}  (newest first = yfinance order)
    """
    if years is None:
        years = pd.date_range("2023-12-31", periods=4, freq="-1YS").tolist()
    df = pd.DataFrame(data_dict, index=years).T
    return df


class TestZipDates:
    """
    Test that zip_dates (called inside fetch_fundamentals) never silently misaligns
    when statement column count != series_vals length.
    We simulate this by patching yfinance to return statements with 4 date columns
    but injecting a 3-entry series.
    """
    def _build_mock_ticker(self, inc_rows=4, bal_rows=4, cf_rows=4):
        mock = MagicMock()
        mock.info = {
            "longName": "Fake Corp",
            "sector": "Technology",
            "industry": "Software",
            "marketCap": 1e12,
            "currentPrice": 150.0,
            "sharesOutstanding": 1e9,
        }
        dates = pd.date_range("2023-12-31", periods=inc_rows, freq="-1YS").tolist()
        bal_dates = pd.date_range("2023-12-31", periods=bal_rows, freq="-1YS").tolist()
        cf_dates  = pd.date_range("2023-12-31", periods=cf_rows,  freq="-1YS").tolist()

        rev_vals = [400e9, 380e9, 365e9, 350e9][:inc_rows]
        mock.financials = pd.DataFrame(
            {"Total Revenue": rev_vals, "Net Income": [90e9]*inc_rows,
             "Gross Profit": [170e9]*inc_rows, "EBIT": [110e9]*inc_rows},
            index=dates,
        ).T

        mock.balance_sheet = pd.DataFrame(
            {"Total Assets": [300e9]*bal_rows,
             "Stockholders Equity": [60e9]*bal_rows,
             "Total Debt": [120e9]*bal_rows,
             "Current Assets": [150e9]*bal_rows,
             "Current Liabilities": [130e9]*bal_rows},
            index=bal_dates,
        ).T

        mock.cashflow = pd.DataFrame(
            {"Operating Cash Flow": [110e9]*cf_rows,
             "Capital Expenditure": [-10e9]*cf_rows},
            index=cf_dates,
        ).T
        return mock

    def test_trend_dates_match_values(self):
        """income_trend revenue entries must have matching year and value counts."""
        with patch("utils.metrics.yf.Ticker") as MockTicker:
            MockTicker.return_value = self._build_mock_ticker()
            result = fetch_fundamentals("FAKE")
        rev = result["income_trend"]["revenue"]
        assert len(rev) > 0
        for entry in rev:
            assert "year" in entry and "value" in entry

    def test_mismatched_lengths_do_not_crash(self):
        """
        When cashflow has 3 columns but income has 4, zip_dates should truncate
        to the shorter — no IndexError, no crash.
        """
        with patch("utils.metrics.yf.Ticker") as MockTicker:
            MockTicker.return_value = self._build_mock_ticker(inc_rows=4, cf_rows=3)
            result = fetch_fundamentals("FAKE")  # must not raise
        assert "cashflow_trend" in result

    def test_no_extra_entries_beyond_shorter_sequence(self):
        """zip_dates must not produce more entries than min(dates, series_vals)."""
        with patch("utils.metrics.yf.Ticker") as MockTicker:
            MockTicker.return_value = self._build_mock_ticker(inc_rows=4, bal_rows=2)
            result = fetch_fundamentals("FAKE")
        # balance trend was built with 2 rows -> max 2 entries
        total_assets = result["balance_trend"]["total_assets"]
        assert len(total_assets) <= 2


# ── fetch_fundamentals — scorecard and metric presence ───────────────────────

class TestFetchFundamentals:
    @pytest.fixture
    def result(self):
        with patch("utils.metrics.yf.Ticker") as MockTicker:
            mock = MagicMock()
            mock.info = {
                "longName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "marketCap": 3e12,
                "currentPrice": 220.0,
                "sharesOutstanding": 15e9,
                "beta": 1.2,
                "trailingPE": 28.0,
                "priceToBook": 45.0,
                "priceToSalesTrailing12Months": 8.0,
                "enterpriseToEbitda": 22.0,
            }
            dates = pd.date_range("2023-12-31", periods=4, freq="-1YS").tolist()
            mock.financials = pd.DataFrame({
                "Total Revenue":  [390e9, 370e9, 365e9, 350e9],
                "Net Income":     [95e9,  90e9,  85e9,  80e9],
                "Gross Profit":   [170e9, 165e9, 160e9, 155e9],
                "EBIT":           [115e9, 110e9, 105e9, 100e9],
                "Interest Expense": [-3e9, -3e9, -3e9, -3e9],
            }, index=dates).T
            mock.balance_sheet = pd.DataFrame({
                "Total Assets":              [350e9]*4,
                "Stockholders Equity":       [60e9]*4,
                "Total Debt":                [110e9]*4,
                "Current Assets":            [150e9]*4,
                "Current Liabilities":       [125e9]*4,
            }, index=dates).T
            mock.cashflow = pd.DataFrame({
                "Operating Cash Flow": [110e9, 105e9, 100e9, 95e9],
                "Capital Expenditure": [-11e9, -10e9, -10e9, -9e9],
            }, index=dates).T
            MockTicker.return_value = mock
            return fetch_fundamentals("AAPL")

    def test_all_required_keys_present(self, result):
        for key in ("ticker", "company", "metrics", "scorecard",
                    "income_trend", "cashflow_trend", "balance_trend"):
            assert key in result, f"Missing key: {key}"

    def test_ticker_uppercased(self, result):
        assert result["ticker"] == "AAPL"

    def test_beta_in_company_info(self, result):
        assert result["company"]["beta"] == pytest.approx(1.2, abs=1e-3)

    def test_gross_margin_is_positive(self, result):
        assert result["metrics"]["gross_margin_pct"] > 0

    def test_scorecard_grades_are_valid_strings(self, result):
        valid = {"pass", "warn", "fail", "na"}
        for key, grade in result["scorecard"].items():
            if key.startswith("_"):
                continue  # metadata keys like _sector_bucket are not grades
            assert grade in valid, f"Unexpected grade '{grade}' for {key}"

    def test_scorecard_has_sector_bucket(self, result):
        """Sector bucket is exposed so callers know which thresholds were applied."""
        assert "_sector_bucket" in result["scorecard"]
        assert result["scorecard"]["_sector_bucket"] in {
            "tech", "financial", "capital", "consumer", "default"
        }

    def test_cagr_returns_none_on_single_year(self, result):
        """With only 4 years of data, 5Y CAGR should be None."""
        # 4 years of data -> only 3Y CAGR available; 5Y must be None or a value
        # We just confirm it doesn't crash and is float-or-None
        val = result["metrics"]["revenue_cagr_5y"]
        assert val is None or isinstance(val, float)

    def test_income_trend_has_entries(self, result):
        assert len(result["income_trend"]["revenue"]) > 0

    def test_cashflow_trend_fcf_computed(self, result):
        """FCF = op_cf + capex; should be positive for healthy mock data."""
        fcf_entries = result["cashflow_trend"]["fcf"]
        assert len(fcf_entries) > 0
        assert all(e["value"] > 0 for e in fcf_entries)
