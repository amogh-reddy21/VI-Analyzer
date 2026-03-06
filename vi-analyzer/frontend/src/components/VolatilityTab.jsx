import { useState } from "react";
import axios from "axios";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import {
  API, TOOLTIP_STYLE, fmt, fmtPct, isValidTicker, MetricCard, Spinner,
} from "./shared";

export default function VolatilityTab({ period, window_ }) {
  const [ticker, setTicker]           = useState("");
  const [data, setData]               = useState(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState(null);
  const [compareTickers, setCompare]  = useState("");
  const [compareData, setCompareData] = useState(null);
  const [cmpLoading, setCmpLoading]   = useState(false);
  const [cmpError, setCmpError]       = useState(null);
  const [slowLoad, setSlowLoad] = useState(false);

  async function fetchSummary(e) {
    e.preventDefault();
    const sym = ticker.trim().toUpperCase();
    if (!sym) return;
    if (!isValidTicker(sym)) { setError("Invalid ticker symbol."); return; }
    setLoading(true); setSlowLoad(false); const _slowTimer = setTimeout(() => setSlowLoad(true), 5000); setError(null); setData(null);
    try {
      const res = await axios.get(`${API}/stock/${sym}/summary`,
        { params: { period, window: window_ } });
      setData(res.data);
    } catch (err) { setError(err.response?.data?.error || err.message); }
    finally { setLoading(false); setSlowLoad(false); clearTimeout(_slowTimer); }
  }

  async function fetchCompare(e) {
    e.preventDefault();
    const syms = compareTickers.trim().toUpperCase();
    if (!syms) return;
    const invalid = syms.split(",").map(s => s.trim()).filter(s => !isValidTicker(s));
    if (invalid.length) { setCmpError(`Invalid symbols: ${invalid.join(", ")}`); return; }
    setCmpLoading(true); setCmpError(null); setCompareData(null);
    try {
      const res = await axios.get(`${API}/compare`,
        { params: { tickers: syms, period, window: window_ } });
      const arr = Object.entries(res.data).map(([sym, d]) => ({
        ticker: sym,
        "Current HV": d.error ? 0 : +Number(d.current_hv).toFixed(2),
        "Mean HV":    d.error ? 0 : +Number(d.mean_hv).toFixed(2),
      }));
      setCompareData(arr);
    } catch (err) { setCmpError(err.response?.data?.error || err.message); }
    finally { setCmpLoading(false); }
  }

  return (
    <div>
      <form className="search-form" onSubmit={fetchSummary}>
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
          <div className="metrics-grid">
            <MetricCard label="Latest Close"     value={`$${fmt(data.latest_close)}`} accent />
            <MetricCard label="1-Day Change"     value={fmtPct(data.pct_change_1d)} sub="vs prior close" />
            <MetricCard label="52-Week High"     value={`$${fmt(data.high_52w)}`} />
            <MetricCard label="52-Week Low"      value={`$${fmt(data.low_52w)}`} />
            <MetricCard label={`HV ${window_}d`} value={`${fmt(data.current_hv)}%`}
              sub={`Mean: ${fmt(data.mean_hv)}%`} accent />
            <MetricCard label="HV Range"         value={`${fmt(data.min_hv)}% – ${fmt(data.max_hv)}%`}
              sub={`${period} range`} />
          </div>

          <div className="chart-section">
            <h2>{ticker.toUpperCase()} — Price ({period})</h2>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data.price_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#8884d8" }} tickLine={false}
                  interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "#8884d8" }} tickLine={false}
                  domain={["auto","auto"]} tickFormatter={v => `$${v.toFixed(0)}`} />
                <Tooltip contentStyle={TOOLTIP_STYLE}
                  formatter={v => [`$${Number(v).toFixed(2)}`, "Close"]} />
                <Line type="monotone" dataKey="close" stroke="#6c63ff" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-section">
            <h2>{ticker.toUpperCase()} — Historical Volatility ({window_}d rolling, annualised)</h2>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={data.hv_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#8884d8" }} tickLine={false}
                  interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "#8884d8" }} tickLine={false}
                  tickFormatter={v => `${v.toFixed(0)}%`} />
                <Tooltip contentStyle={{ ...TOOLTIP_STYLE, borderColor: "#00d4aa" }}
                  formatter={v => [`${Number(v).toFixed(2)}%`, "HV"]} />
                <Line type="monotone" dataKey="hv" stroke="#00d4aa" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      <div className="chart-section">
        <h2>Multi-Ticker Volatility Comparison</h2>
        <form className="search-form" onSubmit={fetchCompare}>
          <input className="ticker-input wide" value={compareTickers}
            onChange={e => setCompare(e.target.value)}
            placeholder="Comma-separated tickers (e.g. AAPL,MSFT,TSLA)" spellCheck={false} />
          <button className="btn-secondary" type="submit" disabled={cmpLoading}>
            {cmpLoading ? "Loading…" : "Compare"}
          </button>
        </form>
        {cmpError && <div className="error-banner">⚠ {cmpError}</div>}
        {cmpLoading && <Spinner />}
        {compareData && (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={compareData} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
              <XAxis dataKey="ticker" tick={{ fill: "#ccc", fontSize: 13 }} tickLine={false} />
              <YAxis tick={{ fill: "#8884d8", fontSize: 11 }}
                tickFormatter={v => `${v}%`} tickLine={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={v => `${v}%`} />
              <Legend wrapperStyle={{ color: "#ccc" }} />
              <Bar dataKey="Current HV" fill="#6c63ff" radius={[4,4,0,0]} />
              <Bar dataKey="Mean HV"    fill="#00d4aa" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
