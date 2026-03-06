# VI Analyzer — DCF Valuation & Fundamental Screening Platform

Bloomberg Terminal access runs ~$25K/year. This replicates its core DCF and fundamental
screening workflow for individual investors and students — using entirely free, open-source
data — across 19 financial metrics, 7 REST endpoints, and a 4-tab React dashboard.

> **Repo:** [github.com/amoghreddy/vi-analyzer](https://github.com/amoghreddy/vi-analyzer)
> &nbsp;·&nbsp; **Stack:** Python · Flask · React · pytest

---

## Demo

| Tab | What it does |
|-----|-------------|
| **Volatility** | Plots rolling historical volatility (HV) for any ticker; compare up to 10 symbols side-by-side |
| **Valuation** | Runs a two-stage DCF under bear / base / bull scenarios; auto-computes WACC from beta via CAPM |
| **Fundamentals** | Scores 19 metrics (margins, returns, leverage, growth) against **sector-specific** thresholds |
| **Peers** | Fetches all tickers concurrently and renders a side-by-side scorecard comparison |

![Valuation tab — AAPL DCF with β-computed WACC, bear/base/bull scenario cards, and 10-year FCF projection chart](docs/screenshot-valuation.png)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.13 · Flask 3 · gunicorn |
| Data | yfinance · pandas · numpy |
| Frontend | React 19 · Recharts · Axios |
| Tests | pytest · pytest-cov (84% coverage, 109 tests) |

---

## Highlights

### Two-Stage DCF Engine
- **Stage 1 (years 1–5):** projects free cash flow at the user-supplied growth rate `g`
- **Stage 2 (years 6–10):** linearly fades `g → terminal_growth` to avoid cliff-edge terminal assumptions
- **Terminal value:** Gordon Growth Model at year 10, discounted at WACC
- Raises a descriptive `422` error for negative/zero FCF, suggesting `EV/EBITDA` or `P/S` as alternatives

### Full WACC Computation (CAPM)
```
Re   = Rf + β × ERP          (Rf = 4.5%,  ERP = 5.5%)
Rd   = interest_expense / total_debt   (falls back to Rf + 100 bps spread)
WACC = (E/V) × Re + (D/V) × Rd × (1 − T)
```
Beta is fetched live and used to auto-set WACC before the DCF runs.
The UI shows a **β-computed** badge when WACC was derived from market data rather than a default.

### Sector-Aware Scorecard
Grading `WMT` on the same bar as `AAPL` produces misleading results.
The scorecard maps each ticker's yfinance sector to one of five threshold buckets:

| Bucket | Sectors | Gross Margin pass bar |
|--------|---------|----------------------|
| `tech` | Technology · Communication Services · Healthcare | ≥ 55% |
| `consumer` | Consumer Staples · Consumer Cyclical | ≥ 35% |
| `capital` | Energy · Utilities · Industrials · Real Estate | ≥ 30% |
| `financial` | Financial Services | D/E & current ratio → `na` (not meaningful for banks) |
| `default` | Everything else | ≥ 40% |

The active bucket is returned in the API response and annotated in the UI as *"Graded vs: tech defaults."*

### Sector-Aware DCF Defaults
Default growth assumptions are calibrated per sector — applying 18% bull growth to a utility
is as wrong as 4% to a SaaS company:

| Bucket | Bear g | Base g | Bull g |
|--------|--------|--------|--------|
| `tech` | 7% | 13% | 22% |
| `consumer` | 3% | 7% | 12% |
| `capital` | 2% | 5% | 9% |
| `financial` | 4% | 8% | 13% |

All parameters are still overridable via query string.

### Concurrent Peer Comparison
`/api/peers` fetches up to 8 tickers in parallel using `ThreadPoolExecutor` + `as_completed`,
with per-ticker TTL caching (5 min). Sequential yfinance fetches would take ~10–15s;
concurrent brings it under 3s.

### Data & Scale
Each full analysis pulls up to 10 years of annual financial statements across the income
statement, balance sheet, and cash flow statement — approximately 30–40 yfinance API calls
per request. Results are cached per-ticker for 5 minutes to avoid redundant upstream calls.
The DCF endpoint alone parses 3 financial statements, computes 19 derived metrics, and runs
3 independent scenario projections per request.

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/amoghreddy/vi-analyzer
make install          # creates venv, pip install, npm install

# 2. Configure environment (optional — all defaults work for local dev)
cp vi-analyzer/backend/.env.example vi-analyzer/backend/.env

# 3. Start both servers
make dev-backend      # Flask on :5000  (terminal 1)
make dev-frontend     # React on :3000  (terminal 2)

# Or concurrently (requires GNU make):
make dev
```

Open [http://localhost:3000](http://localhost:3000).

> **macOS note:** If port 5000 is blocked by AirPlay Receiver, disable it in
> System Settings → General → AirDrop & Handoff, or change the Flask port in `config.py`.

---

## Production

```bash
make serve   # gunicorn -w 2 -t 120 --bind 0.0.0.0:5000
```

> **Cache note:** The in-process TTL cache is per-worker. Use Redis/Memcached behind
> gunicorn in a multi-worker deployment to share cache state across processes.
> The swap point is documented in `routes/__init__.py`.

---

## API Reference

All endpoints are prefixed `/api`.
Ticker symbols are validated server-side against `^[A-Z][A-Z0-9.\-]{0,5}$` —
invalid symbols return `400` before any data is fetched.

---

### `GET /health`
```json
{ "status": "ok" }
```

---

### `GET /stock/<ticker>/volatility`
Annualised historical volatility (%) using a rolling log-return standard deviation.

**Formula:** `HV = σ(log(Pₜ / Pₜ₋₁), window) × √252 × 100`

| Param | Default | Accepted values |
|-------|---------|----------------|
| `period` | `1y` | `1mo` `3mo` `6mo` `1y` `2y` `5y` |
| `window` | `21` | Integer 5–252 |

```json
{
  "ticker": "AAPL",
  "current_hv": 22.31,
  "mean_hv": 19.84,
  "min_hv": 11.02,
  "max_hv": 38.47,
  "window_days": 21,
  "hv_series": [{ "date": "2025-03-03", "hv": 22.31 }, "..."]
}
```

---

### `GET /stock/<ticker>/fundamentals`
19 metrics, sector-aware scorecard grades, and 10-year financial trend series.
Results cached 5 minutes.

```json
{
  "ticker": "AAPL",
  "company": {
    "name": "Apple Inc.", "sector": "Technology",
    "market_cap": 3200000000000, "price": 213.49, "beta": 1.24
  },
  "metrics": {
    "gross_margin_pct": 46.21,
    "operating_margin_pct": 31.51,
    "roic_pct": 54.33,
    "revenue_cagr_3y": 0.074,
    "...": "19 metrics total"
  },
  "scorecard": {
    "gross_margin_pct": "pass",
    "debt_to_equity": "warn",
    "_sector_bucket": "tech",
    "...": "grade per metric"
  },
  "income_trend":   { "revenue": [...], "net_income": [...] },
  "cashflow_trend": { "fcf": [...], "operating_cf": [...] },
  "balance_trend":  { "total_assets": [...], "total_debt": [...] }
}
```

**Scorecard grades:** `pass` · `warn` · `fail` · `na`

---

### `GET /stock/<ticker>/dcf`
Bear / base / bull intrinsic value using a two-stage DCF with Gordon Growth terminal value.

| Param | Default | Description |
|-------|---------|-------------|
| `base_g` | sector-derived | Base FCF growth rate (e.g. `0.12`) |
| `base_wacc` | CAPM-derived | WACC override (e.g. `0.09`) |
| `base_tg` | sector-derived | Terminal growth rate |
| `bear_g` / `bull_g` | sector-derived | Same for other scenarios |
| `bear_wacc` / `bull_wacc` | base ± 1% | WACC for other scenarios |

```json
{
  "ticker": "AAPL",
  "current_price": 213.49,
  "wacc_auto": 0.0932,
  "sector_bucket": "tech",
  "verdict": "overvalued",
  "scenarios": {
    "base": {
      "intrinsic_value": 198.14,
      "margin_of_safety": -7.2,
      "growth_rate": 0.13,
      "wacc": 0.0932,
      "growth_fade": "Y6-10",
      "projected_fcf": [
        { "year": 1, "rate": 0.13, "fcf": 120456000000, "pv": 110418000000 },
        "..."
      ]
    },
    "bear": { "..." },
    "bull": { "..." }
  }
}
```

**Verdict scale:**

| Verdict | Margin of Safety |
|---------|-----------------|
| `strong_buy` | MoS ≥ 30% |
| `buy` | MoS ≥ 10% |
| `fair_value` | −10% to +10% |
| `overvalued` | MoS ≤ −10% |
| `significantly_overvalued` | MoS ≤ −30% |

**HTTP errors:** `400` invalid ticker · `422` negative/zero FCF · `500` upstream failure

---

### `GET /compare?tickers=AAPL,MSFT,NVDA`
Multi-ticker historical volatility comparison. Max 10 tickers.
Accepts same `period` and `window` params as `/volatility`.

---

### `GET /peers?tickers=AAPL,MSFT,GOOGL`
Side-by-side fundamentals scorecard for multiple tickers. Max 8. Fetched concurrently.

---

## Tests

109 pure unit tests with zero network calls — all external data sources mocked via
`unittest.mock`. No yfinance requests are made during the test suite; every ticker
response, financial statement, and info dict is constructed in-process.

```bash
make test           # pytest + coverage report (enforces >= 80% threshold)
make test-fast      # pytest only, no threshold (fast dev loop)
```

```
109 passed in 1.0s

Name                  Stmts   Miss   Cover
------------------------------------------
utils/__init__.py        32      0   100%   HV engine, price summary, fetch
utils/metrics.py        143     16    89%   19 metrics, sector scorecard, CAGR
utils/dcf.py            121     31    74%   two-stage DCF, WACC, scenarios
------------------------------------------
TOTAL                   296     47    84%
```

---

## Architecture

```
vi-analyzer/
├── backend/
│   ├── app.py                  # Flask entry point, CORS, blueprint registration
│   ├── config.py               # Environment-driven config (see .env.example)
│   ├── requirements.txt
│   ├── .env.example            # All supported env variables with descriptions
│   ├── routes/
│   │   └── __init__.py         # 7 endpoints · regex ticker validation · TTL cache · threaded peers
│   ├── utils/
│   │   ├── __init__.py         # Price history fetch · HV computation · price summary
│   │   ├── dcf.py              # Two-stage DCF · full WACC (CAPM) · Gordon Growth terminal value
│   │   └── metrics.py          # 19 metrics · sector-bucketed scorecard · CAGR · trend series
│   └── tests/
│       ├── test_dcf.py         # 35 tests: DCF math, error paths, two-stage rates, MoS boundaries
│       ├── test_metrics.py     # 23 tests: CAGR edge cases, sector bucket, zip_dates alignment
│       ├── test_routes.py      # 29 tests: ticker validation, HTTP semantics, cache TTL expiry
│       └── test_utils.py       # 22 tests: HV correctness, price summary, fetch error handling
└── frontend/
    └── src/
        ├── App.js                      # 64-line shell: tab state, global period/window controls
        └── components/
            ├── shared.jsx              # Constants, formatters, isValidTicker(), MetricCard, Spinner
            ├── VolatilityTab.jsx       # HV line chart, rolling window selector, multi-ticker compare
            ├── ValuationTab.jsx        # DCF form, WACC badge, scenario cards, FCF projection chart
            ├── FundamentalsTab.jsx     # Scorecard grid, revenue/FCF/balance sheet trend charts
            └── PeersTab.jsx            # Concurrent peer fetch, comparison table and bar charts
```

---

## Design Decisions

**Why two-stage DCF instead of a flat 10-year projection?**
A flat growth assumption builds in structural overvaluation for high-growth companies —
the market already prices in that growth decelerates. The linear fade from `g → terminal_growth`
over years 6–10 produces more conservative, defensible intrinsic values without requiring
full analyst-grade multi-stage models.

**Why compute WACC from CAPM instead of asking the user?**
Asking users to input WACC requires them to understand what it is. Auto-computing it from
live beta via `Re = Rf + β × ERP` lowers the barrier to entry while still allowing expert
overrides via the input field. The `β-computed` badge makes the derivation transparent.
The full formula `(E/V)×Re + (D/V)×Rd×(1-T)` is used when balance sheet data is available.

**Why sector-bucketed scorecard thresholds?**
A 25% gross margin is a red flag for a SaaS company and strong for a grocer.
Flat thresholds mislead on any non-tech ticker. The five-bucket system covers all major
yfinance sector strings and is easy to extend with additional buckets or metric overrides.

**Why in-process TTL cache instead of Redis?**
Keeps the dev setup to zero external dependencies — `make install` is the only setup step.
The exact Redis swap point is documented with a comment in `routes/__init__.py`.

**Why yfinance and not a paid data API?**
Free, no API key required, covers 10+ years of audited statements for global tickers.
The tradeoff (rate limits, occasional data gaps) is handled with explicit fallbacks and
descriptive `ValueError` propagation rather than silent `None` returns.

---

## Environment Variables

See [`vi-analyzer/backend/.env.example`](vi-analyzer/backend/.env.example) for the full list.

| Variable | Default | Notes |
|----------|---------|-------|
| `FLASK_DEBUG` | `false` | Set `true` for hot-reload in dev |
| `SECRET_KEY` | `dev-secret-...` | **Must be changed in production** |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `DEFAULT_PERIOD` | `1y` | Default price history lookback |
| `DEFAULT_INTERVAL` | `1d` | Default OHLCV price interval |

---

## Makefile

```bash
make install        # create venv + pip install + npm install
make dev            # start both servers concurrently (GNU make -j2)
make dev-backend    # Flask dev server only, on :5000
make dev-frontend   # React dev server only, on :3000
make serve          # gunicorn -w 2 -t 120 --bind 0.0.0.0:5000
make test           # pytest + coverage report (>= 80% enforced)
make test-fast      # pytest only, no coverage threshold
make smoke-test     # curl /health + /stock/AAPL/dcf against a live server
```

---

*Data provided by Yahoo Finance via yfinance. Not financial advice.*
