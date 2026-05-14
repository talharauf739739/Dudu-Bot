"""
Historical OHLC data fetcher via yfinance.
Supports all 11 ForgeX instruments across 1m / 5m / 1h / 1d timeframes.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

# ── Symbol mapping ─────────────────────────────────────────────────────────────
SYMBOL_MAP: dict[str, str] = {
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    # Indices
    "NAS100":  "^NDX",
    "NASDAQ":  "^NDX",
    "US30":    "^DJI",
    "US500":   "^GSPC",
    "SPX":     "^GSPC",
}

# yfinance interval → max lookback days
MAX_LOOKBACK: dict[str, int] = {
    "1m":  7,
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  730,
    "1d":  3650,
}

# ForgeX TF name → yfinance interval
TF_MAP: dict[str, str] = {
    "1min":  "5m",    # yfinance 1m only goes 7 days; use 5m as proxy
    "5min":  "5m",
    "15min": "15m",
    "1h":    "1h",
    "1hr":   "1h",
    "4h":    "1h",    # yfinance has no 4h; use 1h and display note
    "1d":    "1d",
}


def fetch_ohlc(
    symbol: str,
    timeframe: str = "5min",
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: int = 60,
) -> pd.DataFrame:
    """
    Fetch OHLC candles for a symbol.

    Returns DataFrame with columns:
        open, high, low, close, volume
    Index: datetime (UTC)
    """
    ticker = SYMBOL_MAP.get(symbol.upper(), symbol)
    interval = TF_MAP.get(timeframe, "5m")
    max_days = MAX_LOOKBACK.get(interval, 60)

    if end is None:
        end_dt = datetime.utcnow()
    else:
        end_dt = datetime.strptime(end, "%Y-%m-%d")

    if start is None:
        actual_days = min(days, max_days)
        start_dt = end_dt - timedelta(days=actual_days)
    else:
        start_dt = datetime.strptime(start, "%Y-%m-%d")

    try:
        df = yf.download(
            ticker,
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            print(f"[DataFetcher] No data for {symbol} ({ticker})")
            return pd.DataFrame()

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [c.lower() for c in df.columns]
        df.index.name = "datetime"
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df = df.sort_index()
        print(f"[DataFetcher] {symbol} | {interval} | {len(df)} candles")
        return df

    except Exception as e:
        print(f"[DataFetcher] Error fetching {symbol}: {e}")
        return pd.DataFrame()


def fetch_multi(
    symbols: list[str],
    timeframe: str = "5min",
    days: int = 60,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLC for multiple symbols. Returns {symbol: DataFrame}."""
    return {s: fetch_ohlc(s, timeframe, days=days) for s in symbols}


def resample_to_sessions(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split DataFrame into London and NY session candles."""
    if df.empty:
        return {"LONDON": pd.DataFrame(), "NY": pd.DataFrame()}
    df_utc = df.copy()
    if df_utc.index.tz is None:
        df_utc.index = df_utc.index.tz_localize("UTC")
    london = df_utc.between_time("08:00", "11:59")
    ny = df_utc.between_time("13:30", "20:59")
    return {"LONDON": london, "NY": ny}
