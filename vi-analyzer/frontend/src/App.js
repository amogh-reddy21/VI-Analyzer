import { useState } from "react";
import { PERIODS, WINDOWS } from "./components/shared";
import VolatilityTab    from "./components/VolatilityTab";
import ValuationTab     from "./components/ValuationTab";
import FundamentalsTab  from "./components/FundamentalsTab";
import PeersTab         from "./components/PeersTab";
import "./App.css";

const TABS = ["Volatility", "Valuation", "Fundamentals", "Peers"];

export default function App() {
  const [tab,     setTab]  = useState(0);
  const [period,  setPeriod] = useState("1y");
  const [window_, setWin]    = useState(21);

  return (
    <div className="app">
      <header className="app-header">
        <h1>VI Analyzer <span className="badge">Financial Intelligence Platform</span></h1>
        <p className="subtitle">
          DCF valuation · Margin-of-safety screening · 15+ fundamental metrics · Historical volatility
        </p>
      </header>

      <div className="global-controls">
        <select className="select" value={period}
          onChange={e => setPeriod(e.target.value)}>
          {PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select className="select" value={window_}
          onChange={e => setWin(Number(e.target.value))}>
          {WINDOWS.map(w => <option key={w} value={w}>{w}d HV window</option>)}
        </select>
      </div>

      <div className="tab-bar">
        {TABS.map((t, i) => (
          <button key={t}
            className={`tab-btn${tab === i ? " active" : ""}`}
            onClick={() => setTab(i)}>
            {t}
          </button>
        ))}
      </div>

      <div className="tab-content">
        {tab === 0 && <VolatilityTab   period={period} window_={window_} />}
        {tab === 1 && <ValuationTab    period={period} window_={window_} />}
        {tab === 2 && <FundamentalsTab period={period} window_={window_} />}
        {tab === 3 && <PeersTab        period={period} window_={window_} />}
      </div>

      <footer className="app-footer">
        <p>
          VI Analyzer · Data via{" "}
          <a href="https://finance.yahoo.com" target="_blank" rel="noreferrer">
            Yahoo Finance
          </a>{" "}
          · Not financial advice
        </p>
      </footer>
    </div>
  );
}
