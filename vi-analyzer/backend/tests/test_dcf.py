"""
tests/test_dcf.py
Unit tests for utils/dcf.py — DCF engine correctness and error handling.
"""
import math
import pytest
from unittest.mock import patch, MagicMock

# The tests patch yfinance so no network calls are made
from utils.dcf import compute_dcf, _mos_verdict, _two_stage_rates, _safe


# ── _safe ────────────────────────────────────────────────────────────────────

class TestSafe:
    def test_rounds_float(self):
        assert _safe(3.14159, 2) == 3.14

    def test_returns_none_for_none(self):
        assert _safe(None) is None

    def test_returns_none_for_nan(self):
        assert _safe(float("nan")) is None

    def test_returns_none_for_string(self):
        assert _safe("abc") is None

    def test_zero_is_valid(self):
        assert _safe(0) == 0.0


# ── _two_stage_rates ─────────────────────────────────────────────────────────

class TestTwoStageRates:
    def test_length(self):
        rates = _two_stage_rates(0.15, 0.03, years=10, fade_start=5)
        assert len(rates) == 10

    def test_first_stage_flat(self):
        rates = _two_stage_rates(0.15, 0.03, years=10, fade_start=5)
        assert all(r == 0.15 for r in rates[:5])

    def test_last_rate_equals_terminal(self):
        rates = _two_stage_rates(0.15, 0.03, years=10, fade_start=5)
        assert rates[-1] == pytest.approx(0.03, abs=1e-9)

    def test_fade_is_monotonically_decreasing(self):
        rates = _two_stage_rates(0.20, 0.03, years=10, fade_start=5)
        fade = rates[5:]
        assert all(fade[i] >= fade[i+1] for i in range(len(fade)-1))

    def test_no_fade_when_g_equals_tg(self):
        rates = _two_stage_rates(0.05, 0.05, years=10, fade_start=5)
        assert all(r == pytest.approx(0.05) for r in rates)


# ── _mos_verdict ─────────────────────────────────────────────────────────────

class TestMosVerdict:
    def test_strong_buy_at_boundary(self):
        assert _mos_verdict(30)  == "strong_buy"
    def test_strong_buy_above(self):
        assert _mos_verdict(50)  == "strong_buy"
    def test_buy(self):
        assert _mos_verdict(20)  == "buy"
    def test_buy_at_boundary(self):
        assert _mos_verdict(10)  == "buy"
    def test_fair_value(self):
        assert _mos_verdict(0)   == "fair_value"
    def test_fair_value_negative(self):
        assert _mos_verdict(-5)  == "fair_value"
    def test_fair_value_boundary(self):
        assert _mos_verdict(-10) == "fair_value"
    def test_overvalued(self):
        assert _mos_verdict(-20) == "overvalued"
    def test_overvalued_boundary(self):
        assert _mos_verdict(-30) == "overvalued"
    def test_significantly_overvalued(self):
        assert _mos_verdict(-50) == "significantly_overvalued"
    def test_none_returns_unknown(self):
        assert _mos_verdict(None) == "unknown"


# ── compute_dcf — error paths ─────────────────────────────────────────────────

def _make_mock_ticker(fcf=None, shares=1e9, price=100.0, cf_df=None):
    """Build a yfinance Ticker mock with configurable FCF."""
    mock = MagicMock()
    info = {}
    if fcf is not None:
        info["freeCashflow"] = fcf
    info["sharesOutstanding"] = shares
    info["currentPrice"]      = price
    mock.info = info
    mock.cashflow = cf_df
    return mock


class TestComputeDcfErrors:
    def test_raises_when_no_fcf_data(self):
        """No FCF in info AND no cashflow statement -> ValueError."""
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            MockTicker.return_value = _make_mock_ticker(fcf=None, cf_df=None)
            with pytest.raises(ValueError, match="no free cash flow data"):
                compute_dcf("FAKE")

    def test_raises_when_fcf_is_negative(self):
        """Negative FCF should raise ValueError with a helpful message."""
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            MockTicker.return_value = _make_mock_ticker(fcf=-500_000_000, cf_df=None)
            with pytest.raises(ValueError, match="negative/zero"):
                compute_dcf("FAKE")

    def test_raises_when_fcf_is_zero(self):
        """Zero FCF should raise ValueError."""
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            mock = _make_mock_ticker(fcf=None, cf_df=None)
            mock.info["freeCashflow"] = 0
            MockTicker.return_value = mock
            with pytest.raises(ValueError, match="negative/zero"):
                compute_dcf("FAKE")

    def test_raises_when_shares_missing(self):
        """Missing shares outstanding -> ValueError."""
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            mock = _make_mock_ticker(fcf=1_000_000_000, shares=None, cf_df=None)
            mock.info.pop("sharesOutstanding", None)
            mock.info.pop("impliedSharesOutstanding", None)
            MockTicker.return_value = mock
            with pytest.raises(ValueError, match="shares outstanding"):
                compute_dcf("FAKE")

    def test_wacc_below_terminal_growth_returns_error_dict(self):
        """WACC <= terminal_growth should not crash; scenario gets error key."""
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            MockTicker.return_value = _make_mock_ticker(fcf=1_000_000_000)
            bad_scenarios = {
                "base": {"growth_rate": 0.10, "terminal_growth": 0.12, "wacc": 0.09},
            }
            result = compute_dcf("FAKE", scenarios=bad_scenarios)
            assert "error" in result["scenarios"]["base"]


# ── compute_dcf — happy path ──────────────────────────────────────────────────

class TestComputeDcfHappyPath:
    @pytest.fixture
    def dcf_result(self):
        with patch("utils.dcf.yf.Ticker") as MockTicker:
            MockTicker.return_value = _make_mock_ticker(
                fcf=100_000_000_000,   # $100B FCF (AAPL-ish)
                shares=15_000_000_000, # 15B shares
                price=200.0,
            )
            return compute_dcf("FAKE")

    def test_returns_all_scenarios(self, dcf_result):
        assert set(dcf_result["scenarios"].keys()) == {"bear", "base", "bull"}

    def test_base_intrinsic_is_positive(self, dcf_result):
        assert dcf_result["scenarios"]["base"]["intrinsic_value"] > 0

    def test_bull_iv_greater_than_bear_iv(self, dcf_result):
        bear_iv = dcf_result["scenarios"]["bear"]["intrinsic_value"]
        bull_iv = dcf_result["scenarios"]["bull"]["intrinsic_value"]
        assert bull_iv > bear_iv

    def test_projected_fcf_has_10_years(self, dcf_result):
        assert len(dcf_result["scenarios"]["base"]["projected_fcf"]) == 10

    def test_two_stage_fade_in_projection(self, dcf_result):
        """Years 6-10 growth rates should be strictly less than year 1-5 rate."""
        proj = dcf_result["scenarios"]["base"]["projected_fcf"]
        early_rate = proj[0]["rate"]  # year 1, should equal base_g=0.10
        late_rate  = proj[9]["rate"]  # year 10, should equal terminal_growth=0.03
        assert early_rate == pytest.approx(0.10, abs=1e-6)
        assert late_rate  == pytest.approx(0.03, abs=1e-6)

    def test_margin_of_safety_formula(self, dcf_result):
        """MoS = (IV - price) / IV * 100."""
        s = dcf_result["scenarios"]["base"]
        expected_mos = (s["intrinsic_value"] - s["current_price"]) / s["intrinsic_value"] * 100
        assert s["margin_of_safety"] == pytest.approx(expected_mos, abs=0.01)

    def test_verdict_present(self, dcf_result):
        assert dcf_result["verdict"] in {
            "strong_buy", "buy", "fair_value", "overvalued",
            "significantly_overvalued", "unknown",
        }

    def test_ticker_uppercased(self, dcf_result):
        assert dcf_result["ticker"] == "FAKE"

    def test_total_pv_equals_sum_of_parts(self, dcf_result):
        """total_pv should equal sum(projected pvs) + terminal_pv."""
        s = dcf_result["scenarios"]["base"]
        computed = sum(p["pv"] for p in s["projected_fcf"]) + s["terminal_pv"]
        assert s["total_pv"] == pytest.approx(computed, rel=1e-3)
