# VI Analyzer — Volatility Intelligence

A full-stack web app for computing and visualising **historical volatility (HV)** of equities using real market data from Yahoo Finance.

---

## What it does

- Fetches OHLCV data for any ticker via `yfinance`
- Computes annualised rolling historical volatility: `HV = σ(log returns, N days) × √252`
- Displays price and HV time-series charts
- Shows key metrics: latest close, 1-day change, 52-week high/low, average volume
- Compares volatility across multiple tickers side-by-side

---

## Stack

| Layer    | Tech                                |
|----------|-------------------------------------|
| Backend  | Python 3.13, Flask, yfinance, pandas, numpy |
| Frontend | React 19, recharts, axios           |

---

## Running locally

### 1 — Backend

```bash
cd vi-analyzer/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# (optional) copy and edit environment variables
cp .env.example .env

python3 app.py
# Server starts on http://127.0.0.1:5000
```

### 2 — Frontend

```bash
cd vi-analyzer/frontend
npm install
npm start
# Opens http://localhost:3000
```

---

## API Endpoints

### `GET /api/health`
```json
{ "status": "ok" }
```

### `GET /api/stock/<TICKER>/volatility`
Query params: `period` (default `1y`), `window` (default `21`)

```bash
curl "http://127.0.0.1:5000/api/stock/AAPL/volatility?period=3mo&window=21"
```

### `GET /api/stock/<TICKER>/summary`
Returns price metrics + volatility series (used by the main chart view).

```bash
curl "http://127.0.0.1:5000/api/stock/TSLA/summary?period=1y&window=21"
```

### `GET /api/compare`
Query params: `tickers` (comma-separated, max 10), `period`, `window`

```bash
curl "http://127.0.0.1:5000/api/compare?tickers=AAPL,MSFT,TSLA&period=6mo&window=21"
```

---

## Valid parameter values

| Param    | Allowed values                         |
|----------|----------------------------------------|
| `period` | `1mo` `3mo` `6mo` `1y` `2y` `5y`      |
| `window` | integer between `5` and `252`          |

---

## Project structure

```
vi-analyzer/
├── backend/
│   ├── app.py            # Flask app entry point
│   ├── config.py         # Config class (reads from .env)
│   ├── requirements.txt  # Pinned dependencies
│   ├── .env.example      # Environment variable template
│   ├── routes/
│   │   └── __init__.py   # All API endpoints (Blueprint)
│   └── utils/
│       └── __init__.py   # Data fetching + HV computation
└── frontend/
    └── src/
        ├── App.js         # Main React component
        └── App.css        # Dark theme styles
```
