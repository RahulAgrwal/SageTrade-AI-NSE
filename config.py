from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

# --- Upstox Config ---
UPSTOX_CONFIG = [{
    "api_key": os.getenv("UPSTOX_API_KEY"),
    "api_secret": os.getenv("UPSTOX_API_SECRET"),
    "redirect_uri": os.getenv("UPSTOX_REDIRECT_URI"),
    "access_token": os.getenv("UPSTOX_ACCESS_TOKEN"),
}]

# --- LLM (OpenAI) Configuration ---
LLM_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY"),
    "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    "model_for_stock_qty_selection": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    "model_for_stock_selection": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    "temperature": 1,
    "base_url": "https://api.openai.com/v1"
}

# --- Gemini Config ---
GEMINI_LLM_CONFIG = {
    "api_key": os.getenv("GEMINI_API_KEY"),
    "model": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
    "model_for_stock_qty_selection": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
    "model_for_stock_selection": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
    "temperature": 1,
    "max_retries": 3
}

# --- LLM Pricing ---
LLM_PRICING = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.5},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1-mini": {"input": 0.10, "output": 0.40},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-5": {"input": 1.25, "output": 10.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.5": {"input": 75.00, "output": 150.00},
    "deepseek-reasoner": {"input": 0.28, "output": 0.42},
    "deepseek-chat": {"input": 0.28, "output": 0.42},
    "usd_to_inr": {"usd": 1.0, "inr": 84.0}
}


# --- Risk Management ---
RISK_CONFIG = {
    "MAX_PORTFOLIO_EXPOSURE": 100000,  # Max total value of all positions
    "MAX_POSITION_SIZE": 25000,       # Max value for a single stock position
    "STOP_LOSS_PCT": 0.02,            # Sell if a stock drops by 2% from entry price
    "TAKE_PROFIT_PCT": 0.05,          # Sell if a stock rises by 5% from entry price
    "MIN_CONFIDENCE_THRESHOLD": 0.75,  # Minimum confidence score from LLM to place a trade
    "MAX_TRADES_PER_DAY": 20,         # Prevent over-trading
    "MAX_DAILY_LOSS_PCT": 0.02,        # Stop trading if total portfolio is down 2%
    "RISK_PERCENTAGE_FOR_SINGLE_TRADE": 5 # Risk percentage for a single trade
}

# --- Instruments to Trade on if AUTO_PICK_STOCK = False---
NSE_STOCKS =[
    "SILVERBEES",
    # "RELIANCE",
]

# --- Agent Behavior ---
AGENT_CONFIG = {
    "PRODUCT_TYPE": "I",              # <-- CRITICAL CHANGE: 'I' for Intraday
    "DECISION_INTERVAL_SECONDS": 100,  # <-- CHANGE: Much faster decision loop
    "MARKET_CLOSE_TIME": "15:10",      # <-- NEW: Time to square off all positions
    "LEVERAGE_ON_INTRADAY" : 5,
    "AUTO_PICK_STOCK" : True,
    "RANDOM_SELECT_STOCKS" : False, # True for random selection, False to select TOP STOCKS COMPARED WITH AVAILABLE MARGIN
    "SELECT_STOCK_COUNT_TO_COMPARE" : 10,
    "NUMBER_OF_STOCKS_TO_TRADE" : 1,
    "PREVIOUS_DECISIONS_TO_CONSIDER" : 5
}

# --Techincal Instructions---
INTRADAY_TECHNICAL_ANALYZER_CONFIG = {
    "PERIOD" : "3d",
    "INTERVAL" : "5m"
}

# -- Plot Config for Decision Making ---
DECISION_CHART_PLOT_CONFIG = [
    {"PERIOD" : "1d","INTERVAL" : "1m"},
    {"PERIOD" : "3d","INTERVAL" : "5m"},
    {"PERIOD" : "3d","INTERVAL" : "15m"}
]

# --- News API ---
NEWSAPI_CONFIG ={
    "api_key" : os.getenv("NEWS_API_KEY"),
    "top_headlines_limit" : 5
}

# --- Database ---
DATABASE_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
    "port": int(os.getenv("DB_PORT", 5432)),
}