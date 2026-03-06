import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

    # Stock data defaults
    DEFAULT_PERIOD = os.getenv("DEFAULT_PERIOD", "1y")   # lookback window for yfinance
    DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "1d")
    ANNUALIZATION_FACTOR = 252  # trading days per year
