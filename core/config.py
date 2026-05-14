from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anthropic (optional — Groq is used instead)
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    # Groq (primary LLM provider)
    GROQ_API_KEY: str = ""
    GROQ_API_KEY_2: str = ""
    GROQ_API_KEY_3: str = ""

    # TradeLocker
    TRADELOCKER_BASE_URL: str = "https://demo.tradelocker.com/backend-api"
    TRADELOCKER_EMAIL: str = ""
    TRADELOCKER_PASSWORD: str = ""
    TRADELOCKER_SERVER: str = "OSP-DEMO"
    TRADELOCKER_ACCOUNT_ID: str = ""

    # TradingView
    TRADINGVIEW_WEBHOOK_SECRET: str = ""
    TRADINGVIEW_WEBHOOK_PORT: int = 8001

    # News
    NEWSAPI_KEY: str = ""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Google
    GOOGLE_DRIVE_SHEET_ID: str = ""

    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/forgex_db"

    # Active firm
    ACTIVE_PROP_FIRM: str = "FundedNext"
    ACTIVE_ACCOUNT_ID: str = ""

    # Session windows (GMT)
    SESSION_LONDON_START: str = "08:00"
    SESSION_LONDON_END: str = "12:00"
    SESSION_NY_START: str = "13:30"
    SESSION_NY_END: str = "21:00"

    # Risk
    MAX_RISK_PER_TRADE_PCT: float = 1.0
    MIN_SIGNAL_SCORE: float = 7.5
    MIN_WIN_RATE_PCT: float = 65.0

    # MT5 / MetaTrader 5 (Windows only)
    MT5_LOGIN: str = ""
    MT5_PASSWORD: str = ""
    MT5_SERVER: str = ""
    MT5_TERMINAL_PATH: str = ""

    # Exness
    EXNESS_LOGIN: str = ""
    EXNESS_PASSWORD: str = ""
    EXNESS_SERVER: str = ""
    EXNESS_ACCOUNT_TYPE: str = "standard"

    # FastAPI
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # silently ignore unknown .env vars
    )


settings = Settings()
