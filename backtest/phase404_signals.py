"""
Phase-404 Strategy Signal Generator
=====================================
Step 1: Mark Asian session high/low  (20:00–00:00 EST = 01:00–05:00 UTC)
Step 2: Detect liquidity sweep of Asian high or low
Step 3: Confirm Break of Structure (BOS) after sweep
Step 4: Calculate OTE Fibonacci levels (0.5 / 0.618 / 0.75)
         Entry limits placed at each level with scaled R:R targets
         0.5  entry → 1:2 R:R
         0.618 entry → 1:3 R:R
         0.75 entry → 1:4 R:R
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
ASIAN_START_UTC = 1      # 20:00 EST = 01:00 UTC
ASIAN_END_UTC   = 5      # 00:00 EST = 05:00 UTC
BOS_LOOKBACK    = 8      # candles to define recent swing for BOS
SWEEP_CONFIRM   = 1      # candles price must close back inside range to confirm sweep
OTE_LEVELS      = [0.50, 0.618, 0.75]
OTE_RR          = {0.50: 2.0, 0.618: 3.0, 0.75: 4.0}


@dataclass
class AsianRange:
    date:  str
    high:  float
    low:   float
    mid:   float = field(init=False)

    def __post_init__(self):
        self.mid = round((self.high + self.low) / 2, 5)


@dataclass
class Signal:
    timestamp:   pd.Timestamp
    direction:   str          # BUY | SELL
    sweep_price: float        # the wick that swept liquidity
    bos_price:   float        # price where BOS confirmed
    fib_high:    float        # Fib drawn from this
    fib_low:     float        # Fib drawn to this
    asian_high:  float
    asian_low:   float
    entries: list[dict] = field(default_factory=list)
    # entries = [{level, price, sl, tp, rr}]


# ── Asian Range Detection ─────────────────────────────────────────────────────

def get_asian_ranges(df: pd.DataFrame) -> dict[str, AsianRange]:
    """Return {date_str: AsianRange} for each trading day in df."""
    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    asian = df.between_time(f"{ASIAN_START_UTC:02d}:00", f"{ASIAN_END_UTC-1:02d}:59")
    ranges = {}
    for date, group in asian.groupby(asian.index.date):
        if len(group) < 2:
            continue
        date_str = str(date)
        ranges[date_str] = AsianRange(
            date=date_str,
            high=round(float(group["high"].max()), 5),
            low=round(float(group["low"].min()), 5),
        )
    return ranges


# ── Liquidity Sweep Detection ─────────────────────────────────────────────────

def detect_sweep(candle: pd.Series, ar: AsianRange, buffer: float = 0.0) -> Optional[str]:
    """
    Returns 'BEAR' if candle wicked above Asian high then closed BELOW it.
    Returns 'BULL' if candle wicked below Asian low then closed ABOVE it.
    Requires minimum wick of 15% of Asian range to filter noise.
    """
    min_wick = (ar.high - ar.low) * 0.15   # minimum 15% of range

    wick_above = candle["high"] - ar.high
    wick_below = ar.low - candle["low"]

    if wick_above >= min_wick and candle["close"] < ar.high:
        return "BEAR"
    if wick_below >= min_wick and candle["close"] > ar.low:
        return "BULL"
    return None


# ── Break of Structure ────────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame, sweep_idx: int, direction: str) -> Optional[tuple[int, float]]:
    """
    After a sweep, look for BOS in the next BOS_LOOKBACK candles.
    BEAR sweep → BOS = close below the recent swing low (sell bias)
    BULL sweep → BOS = close above the recent swing high (buy bias)
    Returns (bos_idx, bos_price) or None.
    """
    # Swing reference: lowest low / highest high in lookback before sweep
    pre = df.iloc[max(0, sweep_idx - BOS_LOOKBACK): sweep_idx]
    if len(pre) == 0:
        return None

    if direction == "BEAR":
        swing_ref = float(pre["low"].min())
        for j in range(sweep_idx + 1, min(sweep_idx + 20, len(df))):
            if df.iloc[j]["close"] < swing_ref:
                return (j, round(swing_ref, 5))

    elif direction == "BULL":
        swing_ref = float(pre["high"].max())
        for j in range(sweep_idx + 1, min(sweep_idx + 20, len(df))):
            if df.iloc[j]["close"] > swing_ref:
                return (j, round(swing_ref, 5))

    return None


# ── OTE Fibonacci Calculation ─────────────────────────────────────────────────

def calc_ote_entries(fib_high: float, fib_low: float, direction: str, symbol: str) -> list[dict]:
    """
    Draw Fibonacci from fib_high to fib_low.
    For SELL: levels are retracements back UP into the range → sell limits.
    For BUY:  levels are retracements back DOWN into the range → buy limits.
    SL is beyond the sweep extreme. TP scaled by R:R per level.
    """
    rng = fib_high - fib_low
    buf = rng * 0.05   # 5% buffer for SL

    entries = []
    for level in OTE_LEVELS:
        rr = OTE_RR[level]

        if direction == "SELL":
            entry = round(fib_high - level * rng, 5)   # retrace UP then sell
            sl    = round(fib_high + buf, 5)
            sl_dist = abs(sl - entry)
            tp    = round(entry - rr * sl_dist, 5)
        else:  # BUY
            entry = round(fib_low + level * rng, 5)    # retrace DOWN then buy
            sl    = round(fib_low - buf, 5)
            sl_dist = abs(entry - sl)
            tp    = round(entry + rr * sl_dist, 5)

        if sl_dist <= 0:
            continue

        entries.append({
            "level":     level,
            "entry":     entry,
            "sl":        sl,
            "tp":        tp,
            "rr":        rr,
            "sl_dist":   round(sl_dist, 5),
        })

    return entries


# ── Main Signal Generator ─────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, symbol: str) -> list[Signal]:
    """
    Full Phase-404 signal generation pipeline.
    Returns list of Signal objects, one per valid setup.
    """
    if df.empty or len(df) < 20:
        return []

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    asian_ranges = get_asian_ranges(df)
    signals: list[Signal] = []
    used_dates: set[str] = set()   # one setup per day max

    for i in range(BOS_LOOKBACK, len(df)):
        candle = df.iloc[i]
        ts     = df.index[i]
        hour   = ts.hour

        # Only look for sweeps in London / NY (06:00–21:00 UTC)
        if hour < 6 or hour > 21:
            continue

        date_str = str(ts.date())
        if date_str in used_dates:
            continue

        ar = asian_ranges.get(date_str)
        if ar is None:
            continue

        # Asian range must be meaningful (not zero spread)
        if (ar.high - ar.low) < 1e-5:
            continue

        # Detect sweep
        sweep_type = detect_sweep(candle, ar)
        if sweep_type is None:
            continue

        sweep_price = float(candle["high"]) if sweep_type == "BEAR" else float(candle["low"])

        # Detect BOS
        bos = detect_bos(df, i, sweep_type)
        if bos is None:
            continue

        bos_idx, bos_price = bos

        # Build Fibonacci range
        if sweep_type == "BEAR":
            direction = "SELL"
            fib_high  = sweep_price          # wick high (sweep extreme)
            fib_low   = bos_price            # BOS low (structure break)
        else:
            direction = "BUY"
            fib_high  = bos_price            # BOS high
            fib_low   = sweep_price          # wick low (sweep extreme)

        entries = calc_ote_entries(fib_high, fib_low, direction, symbol)
        if not entries:
            continue

        signals.append(Signal(
            timestamp   = df.index[bos_idx],
            direction   = direction,
            sweep_price = round(sweep_price, 5),
            bos_price   = round(bos_price, 5),
            fib_high    = round(fib_high, 5),
            fib_low     = round(fib_low, 5),
            asian_high  = ar.high,
            asian_low   = ar.low,
            entries     = entries,
        ))
        used_dates.add(date_str)

    return signals


# ── Convert to DataFrame for BacktestEngine ──────────────────────────────────

def signals_to_df(signals: list[Signal], entry_level: float = 0.618) -> pd.DataFrame:
    """
    Convert Signal list to a flat DataFrame compatible with BacktestEngine.
    Picks one entry level per signal (default: 0.618).
    """
    records = []
    for sig in signals:
        entry_data = next((e for e in sig.entries if e["level"] == entry_level), None)
        if entry_data is None and sig.entries:
            entry_data = sig.entries[0]
        if entry_data is None:
            continue

        records.append({
            "signal":   sig.direction,
            "entry":    entry_data["entry"],
            "sl":       entry_data["sl"],
            "tp":       entry_data["tp"],
            "risk_rr":  entry_data["rr"],
            "score":    8.0,
            "strategy": "Phase-404",
        })

    if not records:
        return pd.DataFrame(columns=["signal", "entry", "sl", "tp", "risk_rr", "score", "strategy"])

    idx = [s.timestamp for s in signals if any(e["level"] == entry_level or True for e in s.entries)]
    df  = pd.DataFrame(records)
    df.index = pd.DatetimeIndex(idx[:len(df)])
    return df
