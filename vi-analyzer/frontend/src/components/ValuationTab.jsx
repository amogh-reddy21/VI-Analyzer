import { useState } from "react";
import axios from "axios";
import {
  BarChart, Bar, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  Cell, Line,
} from "recharts";
import {
  API, TOOLTIP_STYLE, fmt, isValidTicker, Spinner,
} from "./shared";

const VERDICT_META = {
  strong_buy:               { label: "Strong Buy",               color: "#00d4aa" },
  buy:                      { label: "Buy",                      color: "#4ade80" },
  fair_value:               { label: "Fair Value",               color: "#facc15" },
  overvalued:               { label: "Overvalued",               color: "#fb923c" },
  significantly_overvalued: { label: "Significantly Overvalued", color: "#f87171" },
  unknown:                  { label: "Unknown",                  color: "#8884d8" },
};

// ── WACC helper ───────────────────────────────────────────────────────────────
// Re = Rf + β × ERP   (CAPM)
// WACC ≈ Re  (simplified; full WACC needs D/V weight which backend can provide)
const RF  = 4.5;   // 10-year Treasury yield, %
const ERP = 5.5;   // long-run equity risk premium, %

function computeWacc(beta) {
  if (beta == null || isNaN(beta)) return null;
  return Math.round(RF + beta * ERP);  // return as integer %, e.g. 9
}

export default function ValuationTab({ period, window_ }) {
  const [ticker, setTicker]   = useState("");
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [slowLoad, setSlowLoad] = useState(false);
  const [error, setError]     = useState(null);
  const [bearG, setBearG]     = useState(5);
  const [baseG, setBaseG]     = useState(10);
  const [bullG, setBullG]     = useState(18);
  const [wacc,  setWacc]      = useState(9);
  const [waccSuggested, setWaccSuggested] = useState(null);
  const [sectorBucket, setSectorBucket] = useState(null);

  async function fetchDCF(e) {
    e.preventDefault();
    const sym = ticker.trim().toUpperCase();
    if (!sym) return;
    if (!isValidTicker(sym)) { setError("Invalid ticker symbol."); return; }
    setLoading(true); setSlowLoad(false); const _slowTimer = setTimeout(() => setSlowLoad(true), 5000); setError(null); setData(null); setWaccSuggested(null); setSectorBucket(null);

    // First fetch beta to auto-suggest WACC
    let suggestedWacc = null;
    try {
      const infoRes = await axios.get(`${API}/stock/${sym}/fundamentals`, { params: { period, window: window_ } });
      const beta = infoRes.data?.company?.beta;
      const w = computeWacc(beta);
      if (w !== null && w > 0) {
        suggestedWacc = w;
        setWacc(w);
        setWaccSuggested(w);
      }
    } catch (_) { /* beta fetch is best-effort */ }

    try {
      const effectiveWacc = suggestedWacc ?? wacc;
      const res = await axios.get(`${API}/stock/${sym}/dcf`, {
        params: {
          bear_g:    bearG / 100,
          base_g:    baseG / 100,
          bull_g:    bullG / 100,
          base_wacc: effectiveWacc / 100,
          bear_wacc: (effectiveWacc + 1) / 100,
          bull_wacc: Math.max((effectiveWacc - 1) / 100, 0.04),
        },
      });
      setData(res.data);
      if (res.data?.sector_bucket) setSectorBucket(res.data.sector_bucket);
    } catch (err) { setError(err.response?.data?.error || err.message); }
    finally { setLoading(false); setSlowLoad(false); clearTimeout(_slowTimer); }
  }

  const s = data?.scenarios || {};
  const verdictMeta = VERDICT_META[data?.verdict] || VERDICT_META.unknown;

  const waterfallData = data ? [
    { name: "Bear",  value: s.bear?.intrinsic_value,  color: "#f87171" },
    { name: "Base",  value: s.base?.intrinsic_value,  color: "#6c63ff" },
    { name: "Bull",  value: s.bull?.intrinsic_value,  color: "#00d4aa" },
    { name: "Price", value: data.current_price,        color: "#facc15" },
  ].filter(d => d.value != null) : [];

  const projectionData = s.base?.projected_fcf?.map(p => ({
    year:            `Y${p.year}`,
    "Projected FCF": Math.round(p.fcf / 1e9 * 100) / 100,
    "PV of FCF":     Math.round(p.pv  / 1e9 * 100) / 100,
  })) || [];

  return (
    <div>
      <form className="search-form" onSubmit={fetchDCF}>
        <input className="ticker-input" value={ticker}
          onChange={e => setTicker(e.target.value)}
          placeholder="Ticker (e.g. AAPL)" spellCheck={false} />
        <div className="param-group">
          <label>Bear g%
            <input type="number" className="param-input" value={bearG}
              onChange={e => setBearG(+e.target.value)} min={0} max={50} />
          </label>
          <label>Base g%
            <input type="number" className="param-input" value={baseG}
              onChange={e => setBaseG(+e.target.value)} min={0} max={50} />
          </label>
          <label>Bull g%
            <input type="number" className="param-input" value={bullG}
              onChange={e => setBullG(+e.target.value)} min={0} max={80} />
          </label>
          <label>
            WACC%{waccSuggested != null &&
              <span className="wacc-badge" title="Auto-computed via CAPM: Rf=4.5%, ERP=5.5%">
                &nbsp;β-computed
              </span>}
            <input type="number" className="param-input" value={wacc}
              onChange={e => setWacc(+e.target.value)} min={1} max={30} />
          </label>
        </div>
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "Computing…" : "Value"}
        </button>
      </form>
      {error && <div className="error-banner">⚠ {error}</div>}
      {loading && <Spinner slow={slowLoad} />}

      {data && (
        <>
          <div className="verdict-banner" style={{ borderColor: verdictMeta.color }}>
            <span className="verdict-label" style={{ color: verdictMeta.color }}>
              {verdictMeta.label}
            </span>
            <span className="verdict-sub">
              Base intrinsic: <strong>${fmt(s.base?.intrinsic_value)}</strong>
              &nbsp;|&nbsp;
              Current price: <strong>${fmt(data.current_price)}</strong>
              &nbsp;|&nbsp;
              {sectorBucket && <span className="wacc-badge" style={{background:"#2a2a3e",color:"#8884d8",marginRight:8}}>⚙ {sectorBucket} defaults</span>}
              MoS: <strong>
                {s.base?.margin_of_safety != null
                  ? `${s.base.margin_of_safety.toFixed(1)}%` : "—"}
              </strong>
            </span>
          </div>

          <div className="metrics-grid three">
            {["bear","base","bull"].map(sc => (
              <div key={sc} className={`scenario-card ${sc}`}>
                <span className="scenario-name">
                  {sc.charAt(0).toUpperCase() + sc.slice(1)}
                </span>
                <span className="scenario-iv">${fmt(s[sc]?.intrinsic_value)}</span>
                <span className="scenario-mos">
                  MoS: {s[sc]?.margin_of_safety != null
                    ? `${s[sc].margin_of_safety.toFixed(1)}%` : "—"}
                </span>
                <span className="scenario-meta">
                  {(s[sc]?.growth_rate * 100).toFixed(0)}% growth
                  &nbsp;·&nbsp;
                  {(s[sc]?.wacc * 100).toFixed(0)}% WACC
                  {s[sc]?.growth_fade != null &&
                    <span className="scenario-fade"> · fades Y6–10</span>}
                </span>
              </div>
            ))}
          </div>

          <div className="charts-row">
            <div className="chart-section half">
              <h2>Intrinsic Value vs Price</h2>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={waterfallData}
                  margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                  <XAxis dataKey="name" tick={{ fill: "#ccc", fontSize: 13 }} tickLine={false} />
                  <YAxis tick={{ fill: "#8884d8", fontSize: 11 }}
                    tickFormatter={v => `$${v}`} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE}
                    formatter={v => `$${Number(v).toFixed(2)}`} />
                  <Bar dataKey="value" radius={[6,6,0,0]}
                    label={{ position: "top", fill: "#ccc", fontSize: 11,
                      formatter: v => `$${Number(v).toFixed(0)}` }}>
                    {waterfallData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="chart-section half">
              <h2>10-Year FCF Projection (Base, $B)</h2>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={projectionData}
                  margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                  <XAxis dataKey="year" tick={{ fill: "#8884d8", fontSize: 10 }} tickLine={false} />
                  <YAxis tick={{ fill: "#8884d8", fontSize: 10 }}
                    tickFormatter={v => `$${v}B`} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE}
                    formatter={v => `$${Number(v).toFixed(2)}B`} />
                  <Legend wrapperStyle={{ color: "#ccc" }} />
                  <Bar dataKey="Projected FCF" fill="#6c63ff" radius={[4,4,0,0]} opacity={0.7} />
                  <Line type="monotone" dataKey="PV of FCF" stroke="#00d4aa"
                    dot={false} strokeWidth={2} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
