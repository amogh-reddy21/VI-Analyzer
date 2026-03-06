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

if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=5000)
