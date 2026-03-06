.PHONY: dev dev-backend dev-frontend serve install install-backend install-frontend smoke-test

## Start both servers in dev mode (requires GNU make -j)
dev:
	$(MAKE) -j2 dev-backend dev-frontend

## Start Flask dev server (single-process, for local development only)
dev-backend:
	cd vi-analyzer/backend && source venv/bin/activate && python3 app.py

## Start React dev server
dev-frontend:
	cd vi-analyzer/frontend && npm start

## Start Flask with gunicorn (2 workers, 120s timeout — production-style)
serve:
	cd vi-analyzer/backend && source venv/bin/activate && \
	gunicorn -w 2 -t 120 --bind 0.0.0.0:5000 app:app

## Install all dependencies
install: install-backend install-frontend

## Create venv and install backend dependencies
install-backend:
	cd vi-analyzer/backend && python3 -m venv venv && \
	source venv/bin/activate && pip install -r requirements.txt

## Install frontend dependencies
install-frontend:
	cd vi-analyzer/frontend && npm install

## Run backend unit tests with coverage (fail if < 80%)
test:
	cd vi-analyzer/backend && source venv/bin/activate && \
	python3 -m pytest tests/ -v --cov=utils --cov-report=term-missing --cov-fail-under=80

## Run tests without coverage threshold (fast dev loop)
test-fast:
	cd vi-analyzer/backend && source venv/bin/activate && python3 -m pytest tests/ -v --tb=short

## Smoke-test against a running Flask instance on :5000
smoke-test:
	curl -sf http://127.0.0.1:5000/api/health | python3 -m json.tool
	curl -sf "http://127.0.0.1:5000/api/stock/AAPL/dcf" | python3 -m json.tool | head -30
