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
    """Diagnostic: test Yahoo Finance crumb fetching from this server."""
    import re
    from curl_cffi import requests as cffi_requests
    out = {}
    session = cffi_requests.Session(impersonate="chrome124")
    try:
        r1 = session.get("https://finance.yahoo.com/quote/AAPL/", timeout=20, allow_redirects=True)
        out["yahoo_status"] = r1.status_code
        out["yahoo_url"] = str(r1.url)
        out["html_len"] = len(r1.text)
        html = r1.text
        # Show all contexts around "crumb" to find the right pattern
        contexts = []
        for m in re.finditer(r"[Cc]rumb", html):
            ctx = html[max(0, m.start()-30):m.start()+80]
            contexts.append(ctx)
        out["crumb_contexts"] = contexts[:8]
        # Try all patterns
        patterns = {
            "user_crumb": r'"user":\{"age":[^}]*"crumb":"([^"]{5,25})"',
            "searchCrumb": r'"searchCrumb":"([^"]{5,25})"',
            "generic_crumb": r'"crumb":"([A-Za-z0-9/_.\-]{5,25})"',
        }
        for name, pat in patterns.items():
            m2 = re.search(pat, html)
            out[name] = m2.group(1) if m2 else None
        # also try the API endpoint
        r2 = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        out["getcrumb_status"] = r2.status_code
        out["getcrumb_text"] = r2.text[:50]
    except Exception as e:
        out["error"] = str(e)
    return out

if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=5000)
