"""
Phase-404 OHLCV Data Store — Redis Backend
==========================================
PRIMARY: 1m candles — yfinance limit is 7 days per pull.
         Each weekly run adds 7 more days. Accumulates indefinitely in Redis.

HTF:     1h + daily — used for EMA50 bias filter only.

Accumulation schedule (1m):
  Week 1  → 7 days stored
  Week 4  → 1 month
  Week 8  → 2 months
  Week 26 → 6 months  ← enough for 25+ setups per pair
  Week 52 → 1 year
  Week 104→ 2 years

On first run: downloads 4 × 7-day chunks = ~28 days of history.
Each subsequent run: adds only the new candles since last stored timestamp.

Storage key: phase404:ohlcv:{SYMBOL}:{interval}
Sorted set:  score = unix timestamp, value = JSON OHLCV

Run: python -m backtest.data_store          (update all pairs)
     python -m backtest.data_store status   (show stored ranges)
"""

import sys
import json
import redis
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── Redis connection ──────────────────────────────────────────────────────────
_pool = redis.ConnectionPool(host="localhost", port=6379, db=0, decode_responses=True)

def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


# ── Key helpers ───────────────────────────────────────────────────────────────

def _ohlcv_key(symbol: str, interval: str = "2m") -> str:
    return f"phase404:ohlcv:{symbol}:{interval}"

def _meta_key(symbol: str, interval: str = "2m") -> str:
    return f"phase404:meta:{symbol}:{interval}"


# ── Save / Load ───────────────────────────────────────────────────────────────

def save(symbol: str, df: pd.DataFrame, interval: str = "2m") -> int:
    """
    Append OHLCV dataframe to Redis sorted set.
    Returns number of NEW candles added (duplicates silently skipped).
    """
    if df.empty:
        return 0

    r   = get_redis()
    key = _ohlcv_key(symbol, interval)
    pipe = r.pipeline(transaction=False)

    for ts, row in df.iterrows():
        score = float(ts.timestamp())
        # Timestamp is part of the member string — guarantees uniqueness per candle
        # even when multiple candles have identical OHLCV (common in Forex 1m data)
        value = json.dumps({
            "t": int(score),
            "o": round(float(row["open"]),  6),
            "h": round(float(row["high"]),  6),
            "l": round(float(row["low"]),   6),
            "c": round(float(row["close"]), 6),
            "v": round(float(row.get("volume", 0)), 2),
        })
        pipe.zadd(key, {value: score}, nx=True)   # NX = skip if same timestamp

    results = pipe.execute()
    new_rows = sum(results)

    # Update metadata
    r.hset(_meta_key(symbol, interval), mapping={
        "last_updated": datetime.utcnow().isoformat(),
        "total":        r.zcard(key),
    })
    return new_rows


def load(symbol: str, interval: str = "2m",
         start: pd.Timestamp = None,
         end:   pd.Timestamp = None) -> pd.DataFrame:
    """
    Load OHLCV data from Redis. Returns a DataFrame indexed by UTC timestamp.
    """
    r   = get_redis()
    key = _ohlcv_key(symbol, interval)

    min_score = start.timestamp() if start else "-inf"
    max_score = end.timestamp()   if end   else "+inf"

    raw = r.zrangebyscore(key, min_score, max_score, withscores=True)
    if not raw:
        return pd.DataFrame()

    records = []
    for value, score in raw:
        d = json.loads(value)
        records.append({
            "timestamp": pd.Timestamp(d.get("t", score), unit="s", tz="UTC"),
            "open":  d["o"], "high": d["h"],
            "low":   d["l"], "close": d["c"],
            "volume": d["v"],
        })

    df = pd.DataFrame(records).set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def count(symbol: str, interval: str = "2m") -> int:
    return get_redis().zcard(_ohlcv_key(symbol, interval))


def date_range(symbol: str, interval: str = "2m") -> tuple:
    """Returns (oldest_ts, newest_ts) or (None, None) if empty."""
    r   = get_redis()
    key = _ohlcv_key(symbol, interval)
    oldest = r.zrange(key, 0, 0, withscores=True)
    newest = r.zrange(key, -1, -1, withscores=True)
    if not oldest or not newest:
        return None, None
    return (pd.Timestamp(oldest[0][1], unit="s", tz="UTC"),
            pd.Timestamp(newest[0][1], unit="s", tz="UTC"))


# ── Download & Update ─────────────────────────────────────────────────────────

def _normalize(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    """Normalize a raw yfinance DataFrame."""
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].dropna().sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    return df


def _fetch_chunk_1m(ticker: str,
                    start: pd.Timestamp,
                    end:   pd.Timestamp) -> pd.DataFrame:
    """Fetch one chunk of 1m data between start and end."""
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1m",
            progress=False, auto_adjust=True,
        )
        return _normalize(df)
    except Exception:
        return pd.DataFrame()


def update_1m(symbol: str, ticker: str,
              chunks: int = 4, verbose: bool = True) -> pd.DataFrame:
    """
    Download 1-minute data in 7-day chunks.
    yfinance allows 1m up to ~30 days back (4 × 7-day windows).

    On first run  : downloads 4 chunks = ~28 days of 1m history.
    On later runs : only new candles since last stored timestamp are added
                    (Redis INSERT OR IGNORE deduplicates everything).
    """
    old_n               = count(symbol, "1m")
    old_start, old_end  = date_range(symbol, "1m")

    if verbose:
        if old_end:
            print(f"  1m stored : {old_n:,} candles  "
                  f"({old_start.date()} → {old_end.date()})")
        else:
            print(f"  1m stored : empty — first download ({chunks} × 7-day chunks)")

    now        = pd.Timestamp.utcnow().normalize()
    total_new  = 0
    total_dl   = 0

    for i in range(chunks):
        chunk_end   = now - pd.Timedelta(days=i * 7)
        chunk_start = chunk_end - pd.Timedelta(days=7)
        df_chunk = _fetch_chunk_1m(ticker, chunk_start, chunk_end)
        if df_chunk.empty:
            continue
        total_dl  += len(df_chunk)
        total_new += save(symbol, df_chunk, "1m")

    total_stored       = count(symbol, "1m")
    new_start, new_end = date_range(symbol, "1m")

    if verbose:
        months = round((new_end - new_start).days / 30.4, 1) if new_end else 0
        print(f"  1m result : {total_dl:,} downloaded  |  "
              f"{total_new:,} new  |  "
              f"{total_stored:,} total  "
              f"({new_start.date() if new_start else '?'} → "
              f"{new_end.date() if new_end else '?'}, {months}mo)")

    return load(symbol, "1m")


def update_htf(symbol: str, ticker: str, interval: str = "1h",
               verbose: bool = True) -> pd.DataFrame:
    """Download and cache 1h or daily HTF data for EMA bias."""
    period = "730d" if interval == "1h" else "2y"
    if verbose:
        print(f"  HTF {interval}: downloading...", end=" ", flush=True)
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        df = _normalize(df)
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        if verbose: print("NO DATA")
        return pd.DataFrame()
    save(symbol, df, interval)
    if verbose:
        print(f"{len(df):,} candles stored")
    return load(symbol, interval)


def status_report(symbols: list[str], interval: str = "2m"):
    """Print a status table for all stored symbols."""
    print(f"\n{'─'*65}")
    print(f"  Phase-404 Redis Store  —  interval={interval}")
    print(f"{'─'*65}")
    print(f"  {'Pair':<10} {'Candles':>10}  {'From':<12} {'To':<12}  Months")
    print(f"  {'─'*60}")
    for sym in symbols:
        n = count(sym, interval)
        s, e = date_range(sym, interval)
        if s and e:
            months = round((e - s).days / 30.4, 1)
            print(f"  {sym:<10} {n:>10,}  {str(s.date()):<12} {str(e.date()):<12}  {months}mo")
        else:
            print(f"  {sym:<10} {'—':>10}")
    print(f"{'─'*65}\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from backtest.pair_config import PAIR_CONFIGS

    symbols = list(PAIR_CONFIGS.keys())
    args    = sys.argv[1:]

    if "status" in args:
        status_report(symbols, "1m")
        status_report(symbols, "1h")
        status_report(symbols, "1d")
        sys.exit(0)

    print("\n" + "=" * 65)
    print("  Phase-404 Data Store — Updating all pairs (Redis, 1m)")
    print("=" * 65)

    for symbol, cfg in PAIR_CONFIGS.items():
        print(f"\n[{symbol}]")
        update_1m(cfg.symbol, cfg.ticker, chunks=4, verbose=True)
        update_htf(cfg.symbol, cfg.ticker, interval="1h", verbose=True)
        update_htf(cfg.symbol, cfg.ticker, interval="1d", verbose=True)

    print("\n[Done] Run weekly to keep accumulating 1m data.\n")
    status_report(symbols, "1m")
