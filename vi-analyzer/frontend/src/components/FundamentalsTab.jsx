import { useState } from "react";
import axios from "axios";
import {
  ComposedChart, BarChart, Bar, Area, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  API, TOOLTIP_STYLE, METRIC_LABELS,
  fmt, fmtBig, fmtMetric, isValidTicker,
  MetricCard, GradeChip, Spinner,
} from "./shared";

export default function FundamentalsTab({ period, window_ }) {
  const [ticker, setTicker]   = useState("");
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [slowLoad, setSlowLoad] = useState(false);
  const [error, setError]     = useState(null);

  async function fetchFund(e) {
    e.preventDefault();
    const sym = ticker.trim().toUpperCase();
    if (!sym) return;
    if (!isValidTicker(sym)) { setError("Invalid ticker symbol."); return; }
    setLoading(true); setSlowLoad(false); const _slowTimer = setTimeout(() => setSlowLoad(true), 5000); setError(null); setData(null);
    try {
      const res = await axios.get(`${API}/stock/${sym}/fundamentals`, { params: { period, window: window_ } });
      setData(res.data);
    } catch (err) { setError(err.response?.data?.error || err.message); }
    finally { setLoading(false); setSlowLoad(false); clearTimeout(_slowTimer); }
  }

  const passCount = data ? Object.values(data.scorecard).filter(v => v === "pass").length : 0;
  const total     = data ? Object.values(data.scorecard).filter(v => v !== "na").length  : 0;

  return (
    <div>
      <form className="search-form" onSubmit={fetchFund}>
        <input className="ticker-input" value={ticker}
          onChange={e => setTicker(e.target.value)}
          placeholder="Ticker (e.g. AAPL)" spellCheck={false} />
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "Loading…" : "Analyze"}
        </button>
      </form>
      {error && <div className="error-banner">⚠ {error}</div>}
      {loading && <Spinner slow={slowLoad} />}

      {data && (
        <>
          <div className="company-header">
            <div>
              <h2 className="company-name">{data.company.name}</h2>
              <span className="company-meta">
                {data.company.sector} · {data.company.industry}
              </span>
            </div>
            <div className="company-stats">
              <MetricCard label="Market Cap" value={fmtBig(data.company.market_cap)} />
              <MetricCard label="Price"      value={`$${fmt(data.company.price)}`} accent />
              <MetricCard label="Score"      value={`${passCount}/${total}`}
                sub="metrics passing" accent={passCount / total >= 0.6} />
            </div>
          </div>

          <div className="scorecard-grid">
            {Object.entries(METRIC_LABELS).map(([key, label]) => {
              const grade = data.scorecard[key];
              const val   = data.metrics[key];
              if (val == null && grade === undefined) return null;
              return (
                <div key={key} className="scorecard-row">
                  <span className="sc-label">{label}</span>
                  <span className="sc-value">{fmtMetric(key, val)}</span>
                  {grade && <GradeChip grade={grade} />}
                </div>
              );
            })}
          </div>

          <div className="charts-row">
            <div className="chart-section half">
              <h2>Revenue & Net Income ($B)</h2>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={data.income_trend.revenue?.map((r, i) => ({
                  year:         r.year,
                  Revenue:      +(r.value / 1e9).toFixed(2),
                  "Net Income": data.income_trend.net_income?.[i]?.value != null
                    ? +(data.income_trend.net_income[i].value / 1e9).toFixed(2) : null,
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                  <XAxis dataKey="year" tick={{ fill: "#8884d8", fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: "#8884d8", fontSize: 11 }}
                    tickFormatter={v => `$${v}B`} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE}
                    formatter={v => `$${Number(v).toFixed(2)}B`} />
                  <Legend wrapperStyle={{ color: "#ccc" }} />
                  <Bar dataKey="Revenue"    fill="#6c63ff" radius={[4,4,0,0]} opacity={0.75} />
                  <Line type="monotone" dataKey="Net Income" stroke="#00d4aa"
                    dot={true} strokeWidth={2} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="chart-section half">
              <h2>Free Cash Flow ($B)</h2>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={data.cashflow_trend.fcf?.map(r => ({
                  year: r.year,
                  FCF:  +(r.value / 1e9).toFixed(2),
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                  <XAxis dataKey="year" tick={{ fill: "#8884d8", fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: "#8884d8", fontSize: 11 }}
                    tickFormatter={v => `$${v}B`} tickLine={false} />
                  <Tooltip contentStyle={{ ...TOOLTIP_STYLE, borderColor: "#00d4aa" }}
                    formatter={v => `$${Number(v).toFixed(2)}B`} />
                  <ReferenceLine y={0} stroke="#444" />
                  <Area type="monotone" dataKey="FCF" stroke="#00d4aa"
                    fill="rgba(0,212,170,0.15)" strokeWidth={2} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="chart-section">
            <h2>Balance Sheet — Assets, Equity & Debt ($B)</h2>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.balance_trend.total_assets?.map((r, i) => ({
                year:           r.year,
                "Total Assets": +(r.value / 1e9).toFixed(2),
                Equity: data.balance_trend.total_equity?.[i]?.value != null
                  ? +(data.balance_trend.total_equity[i].value / 1e9).toFixed(2) : null,
                Debt: data.balance_trend.total_debt?.[i]?.value != null
                  ? +(data.balance_trend.total_debt[i].value / 1e9).toFixed(2) : null,
              }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                <XAxis dataKey="year" tick={{ fill: "#8884d8", fontSize: 11 }} tickLine={false} />
                <YAxis tick={{ fill: "#8884d8", fontSize: 11 }}
                  tickFormatter={v => `$${v}B`} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE}
                  formatter={v => `$${Number(v).toFixed(2)}B`} />
                <Legend wrapperStyle={{ color: "#ccc" }} />
                <Bar dataKey="Total Assets" fill="#6c63ff" radius={[4,4,0,0]} opacity={0.7} />
                <Bar dataKey="Equity"       fill="#00d4aa" radius={[4,4,0,0]} opacity={0.7} />
                <Bar dataKey="Debt"         fill="#f87171" radius={[4,4,0,0]} opacity={0.7} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
