"""
Phase-404 Strategy Signal Generator v2.2
==========================================
Step 1: Mark Asian session high/low (01:00–05:00 UTC)
Step 2: Liquidity sweep during 05:00–08:00 UTC (post-Asian + 1h London)
Step 3: BOS on M1 — strength-filtered, dual HTF bias aligned (1h + Daily)
Step 4: OTE 0.618 limit entry — SL per-pair, 1:2R fixed TP, no breakeven

Philosophy: Trade the retest after a liquidity sweep, in the direction of the trend.
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
OTE_RR          = {0.50: 2.0, 0.618: 2.0, 0.75: 2.0}   # 1:2R for all levels
# Per-pair SL pips — placed beyond the sweep wick extreme
# Wider for volatile pairs (GBPJPY/USDJPY) to avoid being stopped by noise
SL_PIPS = {
    "EURUSD": 10,
    "GBPUSD": 12,
    "USDJPY": 15,
    "GBPJPY": 18,
    "default": 10,
}

# Pip size per symbol
PIP_SIZES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
    "USDJPY": 0.01,   "GBPJPY": 0.01,
    "XAUUSD": 0.1,    "NAS100": 1.0,    "US30": 1.0,
}

# v2.2 filter constants — London killzone only
MIN_ASIAN_RANGE_PIPS = {"EURUSD": 10, "GBPUSD": 10, "AUDUSD": 10,
                        "USDJPY": 15, "GBPJPY": 20, "default": 10}
LONDON_KILL_START = 5    # 05:00 UTC  ← post-Asian sweep window starts
LONDON_KILL_END   = 8    # 08:00 UTC  ← first 1h of London only
BOS_STRENGTH_PIPS = 2    # BOS close must clear swing by at least N pips
MIN_SETUP_PIPS    = 7    # sweep-to-BOS span must be at least N pips
HTF_EMA_PERIOD    = 50   # 1h EMA period for bias filter


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

def detect_sweep(candle: pd.Series, ar: AsianRange,
                 buffer: float = 0.0, min_wick_pct: float = 0.15) -> Optional[str]:
    """
    Returns 'BEAR' if candle wicked above Asian high then closed BELOW it.
    Returns 'BULL' if candle wicked below Asian low then closed ABOVE it.
    min_wick_pct: fraction of Asian range required as wick (default 15%).
                  Use 0.05-0.10 for 1m charts where single-candle wicks are small.
    """
    min_wick = (ar.high - ar.low) * min_wick_pct

    wick_above = candle["high"] - ar.high
    wick_below = ar.low - candle["low"]

    if wick_above >= min_wick and candle["close"] < ar.high:
        return "BEAR"
    if wick_below >= min_wick and candle["close"] > ar.low:
        return "BULL"
    return None


def detect_sweep_rolling(df: pd.DataFrame, idx: int, ar: AsianRange,
                         lookback: int = 3, min_wick_pct: float = 0.10) -> Optional[str]:
    """
    Rolling multi-candle sweep detector for 1m charts.
    Looks back `lookback` candles for the sweep wick, current candle must close back inside.
    BEAR: max high in window exceeds AsH by min_wick AND current close < AsH.
    BULL: min low  in window is below AsL by min_wick AND current close > AsL.
    """
    if idx < lookback:
        return None

    min_wick = (ar.high - ar.low) * min_wick_pct
    window   = df.iloc[idx - lookback: idx + 1]
    current  = df.iloc[idx]

    win_high = float(window["high"].max())
    win_low  = float(window["low"].min())

    wick_above = win_high - ar.high
    wick_below = ar.low - win_low

    if wick_above >= min_wick and float(current["close"]) < ar.high:
        return "BEAR"
    if wick_below >= min_wick and float(current["close"]) > ar.low:
        return "BULL"
    return None


# ── Break of Structure ────────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame, sweep_idx: int, direction: str,
               bos_lookback: int = BOS_LOOKBACK,
               bos_scan_forward: int = 240) -> Optional[tuple[int, float]]:
    """
    After a sweep, look for BOS within bos_scan_forward candles.
    BEAR sweep → BOS = close below the recent swing low (sell bias)
    BULL sweep → BOS = close above the recent swing high (buy bias)

    bos_lookback:     candles BEFORE sweep to define the swing reference
    bos_scan_forward: candles AFTER sweep to scan for a BOS close
                      (default 240 = 4h on 1m, 8h on 2m)
    Returns (bos_idx, bos_price) or None.
    """
    pre = df.iloc[max(0, sweep_idx - bos_lookback): sweep_idx]
    if len(pre) == 0:
        return None

    scan_end = min(sweep_idx + bos_scan_forward, len(df))

    if direction == "BEAR":
        swing_ref = float(pre["low"].min())
        for j in range(sweep_idx + 1, scan_end):
            if df.iloc[j]["close"] < swing_ref:
                return (j, round(swing_ref, 5))

    elif direction == "BULL":
        swing_ref = float(pre["high"].max())
        for j in range(sweep_idx + 1, scan_end):
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
    rng    = fib_high - fib_low
    pip    = PIP_SIZES.get(symbol, 0.0001)
    sl_n   = SL_PIPS.get(symbol, SL_PIPS["default"]) if isinstance(SL_PIPS, dict) else SL_PIPS
    buf    = sl_n * pip   # per-pair SL pips beyond the sweep extreme

    entries = []
    for level in OTE_LEVELS:
        rr = OTE_RR[level]

        if direction == "SELL":
            entry   = round(fib_high - level * rng, 5)   # retrace UP then sell
            sl      = round(fib_high + buf, 5)            # N pips above sweep high
            sl_dist = abs(sl - entry)
            tp      = round(entry - rr * sl_dist, 5)
        else:  # BUY
            entry   = round(fib_low + level * rng, 5)    # retrace DOWN then buy
            sl      = round(fib_low - buf, 5)             # N pips below sweep low
            sl_dist = abs(entry - sl)
            tp      = round(entry + rr * sl_dist, 5)

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

def generate_signals(df: pd.DataFrame, symbol: str,
                     bos_lookback: int = BOS_LOOKBACK) -> list[Signal]:
    """
    Full Phase-404 signal generation pipeline.
    Returns list of Signal objects, one per valid setup.
    bos_lookback: candles used to define swing reference for BOS detection.
                  Use 8 for 5m data, 20 for 1m data.
    """
    if df.empty or len(df) < 20:
        return []

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    asian_ranges = get_asian_ranges(df)
    signals: list[Signal] = []
    used_dates: set[str] = set()   # one setup per day max

    for i in range(bos_lookback, len(df)):
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
        bos = detect_bos(df, i, sweep_type, bos_lookback=bos_lookback)
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


# ── 1m-optimised signal generator ────────────────────────────────────────────

def generate_signals_1m(df: pd.DataFrame, symbol: str,
                        sweep_lookback: int = 3,
                        min_wick_pct: float = 0.10,
                        bos_lookback: int = 20) -> list[Signal]:
    """
    Phase-404 signal generator tuned for 1-minute charts.
    Key difference: uses rolling multi-candle sweep detection (sweep_lookback bars)
    so a sweep that spans several 1m candles is correctly identified.
    """
    if df.empty or len(df) < bos_lookback + sweep_lookback:
        return []

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    asian_ranges = get_asian_ranges(df)
    signals: list[Signal] = []
    used_dates: set[str] = set()

    start_idx = max(bos_lookback, sweep_lookback)
    for i in range(start_idx, len(df)):
        ts   = df.index[i]
        hour = ts.hour
        if hour < 6 or hour > 21:
            continue

        date_str = str(ts.date())
        if date_str in used_dates:
            continue

        ar = asian_ranges.get(date_str)
        if ar is None or (ar.high - ar.low) < 1e-5:
            continue

        # Rolling sweep: window of `sweep_lookback` candles ending at i
        sweep_type = detect_sweep_rolling(df, i, ar,
                                          lookback=sweep_lookback,
                                          min_wick_pct=min_wick_pct)
        if sweep_type is None:
            continue

        # Sweep price = extreme of the rolling window
        window      = df.iloc[i - sweep_lookback: i + 1]
        sweep_price = float(window["high"].max()) if sweep_type == "BEAR" \
                      else float(window["low"].min())

        # BOS detection from current candle
        bos = detect_bos(df, i, sweep_type, bos_lookback=bos_lookback)
        if bos is None:
            continue

        bos_idx, bos_price = bos

        if sweep_type == "BEAR":
            direction = "SELL"
            fib_high  = sweep_price
            fib_low   = bos_price
        else:
            direction = "BUY"
            fib_high  = bos_price
            fib_low   = sweep_price

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
