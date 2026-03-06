import { useState } from "react";
import axios from "axios";
import {
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import {
  API, TOOLTIP_STYLE, METRIC_LABELS, IS_GROWTH,
  fmtBig, fmtMetric, isValidTicker,
  GradeChip, Spinner,
} from "./shared";

const PEER_METRICS = [
  "gross_margin_pct","operating_margin_pct","net_margin_pct",
  "roic_pct","revenue_cagr_3y","pe_ratio","ev_ebitda","debt_to_equity",
];
const COLORS = [
  "#6c63ff","#00d4aa","#f87171","#facc15","#fb923c","#a78bfa","#34d399","#60a5fa",
];

export default function PeersTab({ period, window_ }) {
  const [tickers, setTickers] = useState("");
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  async function fetchPeers(e) {
    e.preventDefault();
    const raw = tickers.trim().toUpperCase();
    if (!raw) return;
    const syms = raw.split(",").map(s => s.trim()).filter(Boolean);
    const invalid = syms.filter(s => !isValidTicker(s));
    if (invalid.length) { setError(`Invalid symbols: ${invalid.join(", ")}`); return; }
    setLoading(true); setError(null); setData(null);
    try {
      const res = await axios.get(`${API}/peers`, { params: { tickers: raw } });
      setData(res.data);
    } catch (err) { setError(err.response?.data?.error || err.message); }
    finally { setLoading(false); }
  }

  const syms = data ? Object.keys(data).filter(k => !data[k].error) : [];

  const chartData = PEER_METRICS.map(key => {
    const row = { metric: METRIC_LABELS[key] || key };
    syms.forEach(sym => {
      let val = data[sym]?.metrics?.[key];
      if (val != null && IS_GROWTH.has(key)) val = +(val * 100).toFixed(2);
      else if (val != null) val = +Number(val).toFixed(2);
      row[sym] = val;
    });
    return row;
  });

  return (
    <div>
      <form className="search-form" onSubmit={fetchPeers}>
        <input className="ticker-input wide" value={tickers}
          onChange={e => setTickers(e.target.value)}
          placeholder="Comma-separated peers (e.g. AAPL,MSFT,GOOGL,AMZN)"
          spellCheck={false} />
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "Loading…" : "Compare"}
        </button>
      </form>
      {error && <div className="error-banner">⚠ {error}</div>}
      {loading && <Spinner />}

      {data && syms.length > 0 && (
        <>
          <div className="peers-header">
            {syms.map((sym, i) => (
              <div key={sym} className="peer-tag"
                style={{ borderColor: COLORS[i % COLORS.length] }}>
                <span className="peer-name"
                  style={{ color: COLORS[i % COLORS.length] }}>{sym}</span>
                <span className="peer-company">{data[sym]?.company?.name}</span>
                <span className="peer-sector">{data[sym]?.company?.sector}</span>
                <span className="peer-mktcap">{fmtBig(data[sym]?.company?.market_cap)}</span>
              </div>
            ))}
          </div>

          <div className="chart-section">
            <h2>Peer Metric Comparison</h2>
            <ResponsiveContainer width="100%" height={360}>
              <BarChart data={chartData} layout="vertical"
                margin={{ top: 5, right: 20, left: 140, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#8884d8", fontSize: 10 }} tickLine={false} />
                <YAxis type="category" dataKey="metric"
                  tick={{ fill: "#ccc", fontSize: 11 }} tickLine={false} width={135} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ color: "#ccc" }} />
                {syms.map((sym, i) => (
                  <Bar key={sym} dataKey={sym}
                    fill={COLORS[i % COLORS.length]} radius={[0,4,4,0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="scorecard-table-wrap">
            <h2>Full Scorecard</h2>
            <table className="scorecard-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {syms.map(sym => <th key={sym}>{sym}</th>)}
                </tr>
              </thead>
              <tbody>
                {Object.entries(METRIC_LABELS).map(([key, label]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    {syms.map(sym => (
                      <td key={sym}>
                        <span className="sc-value-sm">
                          {fmtMetric(key, data[sym]?.metrics?.[key])}
                        </span>
                        {data[sym]?.scorecard?.[key] && (
                          <GradeChip grade={data[sym].scorecard[key]} />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
