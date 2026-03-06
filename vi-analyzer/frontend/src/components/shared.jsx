// Shared constants, helpers, and small presentational components
// used across all tab components.

export const API = process.env.REACT_APP_API_URL || "http://127.0.0.1:5000/api";
export const PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];
export const WINDOWS  = [10, 21, 30, 63];

export const METRIC_LABELS = {
  gross_margin_pct:       "Gross Margin",
  operating_margin_pct:   "Operating Margin",
  net_margin_pct:         "Net Margin",
  fcf_margin_pct:         "FCF Margin",
  roe_pct:                "ROE",
  roa_pct:                "ROA",
  roic_pct:               "ROIC",
  debt_to_equity:         "Debt / Equity",
  interest_coverage:      "Interest Coverage",
  current_ratio:          "Current Ratio",
  pe_ratio:               "P/E",
  pb_ratio:               "P/B",
  ps_ratio:               "P/S",
  p_fcf:                  "P/FCF",
  ev_ebitda:              "EV/EBITDA",
  revenue_cagr_3y:        "Revenue CAGR 3Y",
  revenue_cagr_5y:        "Revenue CAGR 5Y",
  fcf_cagr_3y:            "FCF CAGR 3Y",
  net_income_cagr_3y:     "Net Income CAGR 3Y",
};

export const IS_PCT    = new Set(["gross_margin_pct","operating_margin_pct","net_margin_pct",
  "fcf_margin_pct","roe_pct","roa_pct","roic_pct"]);
export const IS_GROWTH = new Set(["revenue_cagr_3y","revenue_cagr_5y","fcf_cagr_3y",
  "net_income_cagr_3y"]);

export const TOOLTIP_STYLE = {
  background: "#1a1a2e",
  border: "1px solid #6c63ff",
  borderRadius: 8,
  fontSize: 12,
};

// ── Formatters ────────────────────────────────────────────────────────────────
export function fmt(n, dec = 2) {
  return n == null ? "—" : Number(n).toFixed(dec);
}
export function fmtPct(n) {
  return n == null ? "—" : `${Number(n) > 0 ? "+" : ""}${Number(n).toFixed(2)}%`;
}
export function fmtBig(n) {
  if (n == null) return "—";
  const v = Number(n);
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (Math.abs(v) >= 1e9)  return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6)  return `$${(v / 1e6).toFixed(2)}M`;
  return `$${v.toLocaleString()}`;
}
export function fmtMetric(key, val) {
  if (val == null) return "—";
  if (IS_PCT.has(key))    return `${fmt(val)}%`;
  if (IS_GROWTH.has(key)) return `${(val * 100).toFixed(1)}%`;
  return fmt(val);
}

// ── Ticker input validation ───────────────────────────────────────────────────
// Accepts 1-6 uppercase letters/dots/hyphens (covers BRK.B, BF-B, etc.)
export function isValidTicker(sym) {
  return /^[A-Z][A-Z0-9.-]{0,5}$/.test(sym.trim().toUpperCase());
}

// ── Presentational components ─────────────────────────────────────────────────
export function MetricCard({ label, value, sub, accent }) {
  return (
    <div className={`metric-card${accent ? " accent" : ""}`}>
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value ?? "—"}</span>
      {sub && <span className="metric-sub">{sub}</span>}
    </div>
  );
}

export function GradeChip({ grade }) {
  const cls = { pass: "chip-pass", warn: "chip-warn", fail: "chip-fail", na: "chip-na" };
  const lbl = { pass: "✓ Pass",   warn: "~ Warn",    fail: "✗ Fail",    na: "N/A" };
  return <span className={`chip ${cls[grade] || "chip-na"}`}>{lbl[grade] || "N/A"}</span>;
}

export function Spinner() {
  return <div className="spinner-wrap"><div className="spinner" /></div>;
}
