"""
Signal generation for all 10 ForgeX strategies.
Each function returns a DataFrame with columns:
  signal    : BUY | SELL | None
  entry     : float
  sl        : float
  tp        : float
  score     : float (1-10 confidence)
  strategy  : str   (strategy ID)
"""

import pandas as pd
import numpy as np
from backtest.indicators import (
    ema, rsi, macd, atr, keltner_channel, vwap,
    heikin_ashi, detect_fvg, detect_order_block,
    detect_bos_choch, london_range
)

SL_BUFFER = 0.0003   # 0.3 pip buffer on SL for forex
INDEX_SL_BUFFER = 0.5  # points buffer for indices


def _index_symbol(symbol: str) -> bool:
    return symbol.upper() in {"NAS100", "US30", "US500", "NASDAQ", "SPX"}


def _sl_buffer(symbol: str) -> float:
    return INDEX_SL_BUFFER if _index_symbol(symbol) else SL_BUFFER


def _rr_target(entry: float, sl: float, direction: str, rr: float) -> float:
    dist = abs(entry - sl)
    return entry + dist * rr if direction == "BUY" else entry - dist * rr


def _score_base(rsi_val: float, direction: str, atr_val: float,
                price: float, body_ratio: float) -> float:
    score = 5.0
    if direction == "BUY":
        if 40 < rsi_val < 60: score += 1.5
        if rsi_val < 45: score += 1.0
    else:
        if 40 < rsi_val < 60: score += 1.5
        if rsi_val > 55: score += 1.0
    if body_ratio > 0.6: score += 1.0
    if atr_val > 0: score += min(1.5, atr_val / price * 1000)
    return round(min(10.0, score), 1)


# ── S-01: ICT Order Block + FVG ───────────────────────────────────────────────

def s01_ict_ob_fvg(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf = _sl_buffer(symbol)
    fvg   = detect_fvg(df)
    ob    = detect_order_block(df)
    rsi_s = rsi(df["close"])
    atr_s = atr(df)

    sigs = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        signal = direction = None
        entry = sl = tp = 0.0

        # Bullish: bull OB + bull FVG
        if ob["bull_ob"].iloc[i - 1] and fvg["bull_fvg"].iloc[i]:
            direction = "BUY"
            entry = row["close"]
            sl = df["low"].iloc[i - 2] - buf
            tp = _rr_target(entry, sl, "BUY", 3.0)
            signal = "BUY"

        # Bearish: bear OB + bear FVG
        elif ob["bear_ob"].iloc[i - 1] and fvg["bear_fvg"].iloc[i]:
            direction = "SELL"
            entry = row["close"]
            sl = df["high"].iloc[i - 2] + buf
            tp = _rr_target(entry, sl, "SELL", 3.0)
            signal = "SELL"

        body_ratio = abs(row["close"] - row["open"]) / max((row["high"] - row["low"]), 0.0001)
        sc = _score_base(rsi_s.iloc[i] if not pd.isna(rsi_s.iloc[i]) else 50,
                         direction or "BUY", atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], body_ratio) if signal else 0

        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-01"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-02: EMA 5/20 + RSI Filter ──────────────────────────────────────────────

def s02_ema_rsi(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf   = _sl_buffer(symbol)
    e5    = ema(df["close"], 5)
    e20   = ema(df["close"], 20)
    rsi_s = rsi(df["close"])
    atr_s = atr(df)
    swing = df["low"].rolling(10).min()
    swing_h = df["high"].rolling(10).max()

    cross_up = (e5 > e20) & (e5.shift(1) <= e20.shift(1))
    cross_dn = (e5 < e20) & (e5.shift(1) >= e20.shift(1))

    sigs = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        signal = None; entry = sl = tp = 0.0
        if cross_up.iloc[i] and rsi_s.iloc[i] > 50:
            signal = "BUY"
            entry  = row["close"]
            sl     = swing.iloc[i] - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)
        elif cross_dn.iloc[i] and rsi_s.iloc[i] < 50:
            signal = "SELL"
            entry  = row["close"]
            sl     = swing_h.iloc[i] + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-02"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-03: SMC — BOS + ChoCH ──────────────────────────────────────────────────

def s03_smc_bos_choch(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf     = _sl_buffer(symbol)
    bos     = detect_bos_choch(df)
    rsi_s   = rsi(df["close"])
    atr_s   = atr(df)

    sigs = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        signal = None; entry = sl = tp = 0.0

        if bos["choch_up"].iloc[i] or bos["bos_up"].iloc[i]:
            signal = "BUY"
            entry  = row["close"]
            sl     = df["low"].rolling(10).min().iloc[i] - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)
        elif bos["choch_dn"].iloc[i] or bos["bos_dn"].iloc[i]:
            signal = "SELL"
            entry  = row["close"]
            sl     = df["high"].rolling(10).max().iloc[i] + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-03"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-04: VWAP Rejection Scalp ────────────────────────────────────────────────

def s04_vwap_rejection(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf    = _sl_buffer(symbol)
    vwap_s = vwap(df)
    rsi_s  = rsi(df["close"])
    atr_s  = atr(df)

    sigs = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        signal = None; entry = sl = tp = 0.0
        v = vwap_s.iloc[i]

        # Touched VWAP from above → SELL
        touched_from_above = (df["low"].iloc[i - 1] <= v) and (df["close"].iloc[i] < v)
        # Touched VWAP from below → BUY
        touched_from_below = (df["high"].iloc[i - 1] >= v) and (df["close"].iloc[i] > v)

        if touched_from_below and rsi_s.iloc[i] > 45:
            signal = "BUY"
            entry  = row["close"]
            sl     = row["low"] - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)
        elif touched_from_above and rsi_s.iloc[i] < 55:
            signal = "SELL"
            entry  = row["close"]
            sl     = row["high"] + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-04"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-05: London Breakout ─────────────────────────────────────────────────────

def s05_london_breakout(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf      = _sl_buffer(symbol)
    lr       = london_range(df)
    atr_s    = atr(df)
    rsi_s    = rsi(df["close"])

    sigs = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        if df.index.tz is not None:
            hour = df.index[i].hour
        else:
            hour = df.index[i].hour

        # Only trade 08:00-10:00 UTC (London open)
        if hour < 8 or hour > 10:
            sigs.append({"datetime": df.index[i], "signal": None, "entry": 0,
                         "sl": 0, "tp": 0, "score": 0, "strategy": "S-05"})
            continue

        rh = lr["range_high"].iloc[i]
        rl = lr["range_low"].iloc[i]
        signal = None; entry = sl = tp = 0.0

        if pd.notna(rh) and pd.notna(rl):
            mid = (rh + rl) / 2
            if row["close"] > rh:
                signal = "BUY"
                entry  = row["close"]
                sl     = mid - buf
                tp     = _rr_target(entry, sl, "BUY", 2.0)
            elif row["close"] < rl:
                signal = "SELL"
                entry  = row["close"]
                sl     = mid + buf
                tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.6) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-05"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-07: Keltner Channel + RSI ───────────────────────────────────────────────

def s07_keltner_rsi(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf   = _sl_buffer(symbol)
    kc    = keltner_channel(df)
    rsi_s = rsi(df["close"])
    atr_s = atr(df)

    sigs = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        signal = None; entry = sl = tp = 0.0

        # Price touches lower Keltner + RSI < 35 → BUY
        if row["low"] <= kc["lower"].iloc[i] and rsi_s.iloc[i] < 40:
            signal = "BUY"
            entry  = row["close"]
            sl     = row["low"] - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)
        # Price touches upper Keltner + RSI > 65 → SELL
        elif row["high"] >= kc["upper"].iloc[i] and rsi_s.iloc[i] > 60:
            signal = "SELL"
            entry  = row["close"]
            sl     = row["high"] + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-07"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-09: MACD + RSI Momentum ─────────────────────────────────────────────────

def s09_macd_rsi(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf    = _sl_buffer(symbol)
    macd_d = macd(df["close"])
    rsi_s  = rsi(df["close"])
    atr_s  = atr(df)
    swing  = df["low"].rolling(10).min()
    swing_h = df["high"].rolling(10).max()

    cross_up = (macd_d["macd"] > macd_d["signal"]) & (macd_d["macd"].shift(1) <= macd_d["signal"].shift(1))
    cross_dn = (macd_d["macd"] < macd_d["signal"]) & (macd_d["macd"].shift(1) >= macd_d["signal"].shift(1))

    sigs = []
    for i in range(30, len(df)):
        row = df.iloc[i]
        signal = None; entry = sl = tp = 0.0

        if cross_up.iloc[i] and rsi_s.iloc[i] > 50:
            signal = "BUY"
            entry  = row["close"]
            sl     = swing.iloc[i] - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)
        elif cross_dn.iloc[i] and rsi_s.iloc[i] < 50:
            signal = "SELL"
            entry  = row["close"]
            sl     = swing_h.iloc[i] + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-09"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── S-10: Heikin-Ashi Pullback ────────────────────────────────────────────────

def s10_heikin_ashi(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    buf  = _sl_buffer(symbol)
    ha   = heikin_ashi(df)
    e20  = ema(df["close"], 20)
    atr_s = atr(df)
    rsi_s = rsi(df["close"])

    sigs = []
    for i in range(20, len(df)):
        row    = df.iloc[i]
        ha_row = ha.iloc[i]
        ha_prev = ha.iloc[i - 1]
        signal = None; entry = sl = tp = 0.0

        # Bullish: previous HA was bearish (pullback), current is bullish + above EMA20
        if (ha_prev["close"] < ha_prev["open"] and
                ha_row["close"] > ha_row["open"] and
                row["close"] > e20.iloc[i]):
            signal = "BUY"
            entry  = row["close"]
            sl     = ha.iloc[max(0, i - 3):i]["low"].min() - buf
            tp     = _rr_target(entry, sl, "BUY", 2.0)

        # Bearish: previous HA was bullish (pullback), current is bearish + below EMA20
        elif (ha_prev["close"] > ha_prev["open"] and
              ha_row["close"] < ha_row["open"] and
              row["close"] < e20.iloc[i]):
            signal = "SELL"
            entry  = row["close"]
            sl     = ha.iloc[max(0, i - 3):i]["high"].max() + buf
            tp     = _rr_target(entry, sl, "SELL", 2.0)

        sc = _score_base(rsi_s.iloc[i], signal or "BUY",
                         atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0,
                         row["close"], 0.5) if signal else 0
        sigs.append({"datetime": df.index[i], "signal": signal, "entry": entry,
                     "sl": sl, "tp": tp, "score": sc, "strategy": "S-10"})
    return pd.DataFrame(sigs).set_index("datetime")


# ── Strategy registry ─────────────────────────────────────────────────────────

STRATEGY_FUNCTIONS: dict[str, callable] = {
    "S-01": s01_ict_ob_fvg,
    "S-02": s02_ema_rsi,
    "S-03": s03_smc_bos_choch,
    "S-04": s04_vwap_rejection,
    "S-05": s05_london_breakout,
    "S-07": s07_keltner_rsi,
    "S-09": s09_macd_rsi,
    "S-10": s10_heikin_ashi,
}


def run_strategy(strategy_id: str, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    fn = STRATEGY_FUNCTIONS.get(strategy_id)
    if fn is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    return fn(df, symbol)
