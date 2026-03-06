from flask import Flask
from flask_cors import CORS
from config import Config
from routes import api

app = Flask(__name__)
app.config.from_object(Config)

CORS(app, origins="*", supports_credentials=False)

app.register_blueprint(api)

@app.route("/")
def index():
    return {"status": "ok", "message": "VI-Analyzer API is running. Use /api/... endpoints."}

@app.route("/api/debug/crumb")
def debug_crumb():
    """Diagnostic endpoint to test Yahoo Finance crumb fetching from this server."""
    from curl_cffi import requests as cffi_requests
    results = {}
    session = cffi_requests.Session(impersonate="chrome124")
    warm_urls = [
        "https://finance.yahoo.com/",
        "https://query2.finance.yahoo.com/v8/finance/chart/AAPL",
    ]
    crumb_urls = [
        "https://query2.finance.yahoo.com/v1/test/getcrumb",
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
    ]
    for warm_url in warm_urls:
        try:
            rw = session.get(warm_url, timeout=15, allow_redirects=True)
            results[f"warm:{warm_url}"] = rw.status_code
            for crumb_url in crumb_urls:
                try:
                    rc = session.get(crumb_url, timeout=10)
                    results[f"crumb:{crumb_url}"] = {"status": rc.status_code, "crumb": rc.text[:20] if rc.status_code == 200 else rc.text[:100]}
                except Exception as ce:
                    results[f"crumb:{crumb_url}"] = {"error": str(ce)}
        except Exception as e:
            results[f"warm:{warm_url}"] = {"error": str(e)}
    return results

if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=5000)
