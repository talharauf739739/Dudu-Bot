"""
Phase-404 v2.2 — Enhanced Backtest (2m data, 60 days ≈ 2 months)
===================================================================
Pairs: EURUSD, GBPUSD, USDJPY, GBPJPY
Enhancements over v2.1:
  • Per-pair SL pips: EUR=10, GBP=12, USDJPY=15, GBPJPY=18
  • Dual HTF trend filter: 1h EMA50 + Daily EMA50 must both align
  • BOS candle body strength: body must be ≥ 40% of candle range
  • Black trade zone box on charts (SL→TP, entry→exit time)
  • Fixed SL/TP — no breakeven

Philosophy: Trade the retest after a liquidity sweep, in the direction of the trend.

Run: python -m backtest.phase404_1m_backtest
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

from backtest.phase404_signals import (
    get_asian_ranges, detect_sweep_rolling, detect_bos,
    calc_ote_entries, Signal,
    PIP_SIZES, MIN_ASIAN_RANGE_PIPS,
    LONDON_KILL_START, LONDON_KILL_END,
    BOS_STRENGTH_PIPS, MIN_SETUP_PIPS, HTF_EMA_PERIOD,
)

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS = {
    "EURUSD": {"ticker": "EURUSD=X", "pip": 0.0001, "pip_val": 10.0},
    "GBPUSD": {"ticker": "GBPUSD=X", "pip": 0.0001, "pip_val": 10.0},
    "USDJPY": {"ticker": "USDJPY=X", "pip": 0.01,   "pip_val": 7.0},
    "GBPJPY": {"ticker": "GBPJPY=X", "pip": 0.01,   "pip_val": 7.0},
}
ACCOUNT_SIZE   = 10_000.0
RISK_PCT       = 1.0
BOS_LOOKBACK   = 20        # 20 × 2m = 40-min swing lookback
SWEEP_LOOKBACK = 5         # 5 × 2m = 10-min rolling sweep window
MIN_WICK_PCT   = 0.08      # 8% of Asian range (realistic for 2m candles)
FORWARD_SCAN   = 2160      # 3 trading days × 720 bars/day (2m)
OTE_ENTRY_LVL  = 0.618     # golden ratio entry
OTE_RR         = 2.0       # 1:2 risk-reward

OUT_DIR = Path(__file__).parent.parent / "data" / "phase404"
OUT_DIR.mkdir(parents=True, exist_ok=True)

C = {
    "bg": "#0a0a12", "bg2": "#0e0e1a", "grid": "#1a1a28",
    "asian": "rgba(100,149,237,0.12)", "asian_l": "#6495ED",
    "sweep": "#FF6B35", "bos": "#FFD700",
    "sell": "#FF4444", "buy": "#00CC66",
    "win": "#00E676", "loss": "#FF1744", "equity": "#00D4AA",
    "be": "#FFD700",
}


# ── Data Fetch ────────────────────────────────────────────────────────────────

def fetch_2m(symbol: str) -> pd.DataFrame:
    """Download 60 days of 2m data (yfinance max for 2m interval)."""
    ticker = SYMBOLS[symbol]["ticker"]
    print(f"  [{symbol}] Downloading 2m data (60 days)...", end=" ", flush=True)
    df = yf.download(ticker, period="60d", interval="2m",
                     progress=False, auto_adjust=True)
    if df.empty:
        print("NO DATA")
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    print(f"{len(df):,} candles  {df.index[0].date()} → {df.index[-1].date()}")
    return df


def fetch_1h_htf(symbol: str) -> pd.DataFrame:
    """Download 1h data for HTF bias (EMA50)."""
    ticker = SYMBOLS[symbol]["ticker"]
    df = yf.download(ticker, period="120d", interval="1h",
                     progress=False, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["close"]].dropna().sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df["ema50"] = df["close"].ewm(span=HTF_EMA_PERIOD, adjust=False).mean()
    return df


def fetch_daily_htf(symbol: str) -> pd.DataFrame:
    """Download daily data for macro trend (EMA50) — reliable lookback via yfinance."""
    ticker = SYMBOLS[symbol]["ticker"]
    df = yf.download(ticker, period="1y", interval="1d",
                     progress=False, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["close"]].dropna().sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df["ema50"] = df["close"].ewm(span=HTF_EMA_PERIOD, adjust=False).mean()
    return df


def get_htf_bias(htf_df: pd.DataFrame, ts: pd.Timestamp) -> str:
    """Return 'BULL', 'BEAR', or 'NEUTRAL' based on 1h EMA50 at timestamp."""
    if htf_df.empty:
        return "NEUTRAL"
    idx = htf_df.index.searchsorted(ts) - 1
    if idx < 0:
        return "NEUTRAL"
    idx = min(idx, len(htf_df) - 1)
    row = htf_df.iloc[idx]
    if pd.isna(row["ema50"]):
        return "NEUTRAL"
    if float(row["close"]) > float(row["ema50"]):
        return "BULL"
    if float(row["close"]) < float(row["ema50"]):
        return "BEAR"
    return "NEUTRAL"


# ── v2.0 Signal Generator ────────────────────────────────────────────────────

def generate_signals_v2(df: pd.DataFrame, symbol: str,
                        htf_df: pd.DataFrame,
                        htf_daily_df: pd.DataFrame = None) -> tuple[list[Signal], list[dict]]:
    """
    Phase-404 v2.2 signal generator.
    Dual HTF trend filter (1h + Daily EMA50) + BOS candle body strength.
    Returns (signals, filter_log) where filter_log explains each rejection.
    """
    if df.empty or len(df) < BOS_LOOKBACK + SWEEP_LOOKBACK:
        return [], []

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    pip       = PIP_SIZES.get(symbol, 0.0001)
    min_range = MIN_ASIAN_RANGE_PIPS.get(symbol,
                    MIN_ASIAN_RANGE_PIPS.get("default", 15)) * pip

    asian_ranges = get_asian_ranges(df)
    signals: list[Signal]  = []
    filter_log: list[dict] = []
    used_dates: set[str]   = set()

    for i in range(BOS_LOOKBACK + SWEEP_LOOKBACK, len(df)):
        ts   = df.index[i]
        hour = ts.hour

        # ── London killzone gate ─────────────────────────────────────────────
        if not (LONDON_KILL_START <= hour < LONDON_KILL_END):
            continue

        date_str = str(ts.date())
        if date_str in used_dates:
            continue

        ar = asian_ranges.get(date_str)
        if ar is None:
            continue

        # ── Minimum Asian range filter ───────────────────────────────────────
        if (ar.high - ar.low) < min_range:
            filter_log.append({"date": date_str, "ts": ts,
                                "reason": f"Asian range too small ({round((ar.high-ar.low)/pip,1)} pips < {MIN_ASIAN_RANGE_PIPS.get(symbol,15)})"})
            continue

        # ── Rolling sweep detection ──────────────────────────────────────────
        sweep_type = detect_sweep_rolling(df, i, ar,
                                          lookback=SWEEP_LOOKBACK,
                                          min_wick_pct=MIN_WICK_PCT)
        if sweep_type is None:
            continue

        window      = df.iloc[i - SWEEP_LOOKBACK: i + 1]
        sweep_price = float(window["high"].max()) if sweep_type == "BEAR" \
                      else float(window["low"].min())

        # ── BOS detection ────────────────────────────────────────────────────
        bos = detect_bos(df, i, sweep_type, bos_lookback=BOS_LOOKBACK)
        if bos is None:
            filter_log.append({"date": date_str, "ts": ts,
                                "reason": "No BOS found within 60 candles"})
            continue

        bos_idx, bos_price = bos
        bos_candle = df.iloc[bos_idx]

        # ── BOS strength filter ──────────────────────────────────────────────
        swing_pre  = df.iloc[max(0, i - BOS_LOOKBACK): i]
        if sweep_type == "BEAR":
            swing_ref  = float(swing_pre["low"].min())
            bos_excess = (swing_ref - float(bos_candle["close"])) / pip
        else:
            swing_ref  = float(swing_pre["high"].max())
            bos_excess = (float(bos_candle["close"]) - swing_ref) / pip

        if bos_excess < BOS_STRENGTH_PIPS:
            filter_log.append({"date": date_str, "ts": ts,
                                "reason": f"BOS too weak ({bos_excess:.1f} pips < {BOS_STRENGTH_PIPS})"})
            continue

        # ── BOS candle body strength — strong directional close required ─────
        c_range = float(bos_candle["high"]) - float(bos_candle["low"])
        c_body  = abs(float(bos_candle["close"]) - float(bos_candle["open"]))
        if c_range > 0 and c_body / c_range < 0.40:
            filter_log.append({"date": date_str, "ts": ts,
                                "reason": f"BOS candle body weak ({c_body/c_range:.0%} < 40%)"})
            continue

        # ── Minimum setup span ───────────────────────────────────────────────
        span_pips = abs(sweep_price - bos_price) / pip
        if span_pips < MIN_SETUP_PIPS:
            filter_log.append({"date": date_str, "ts": ts,
                                "reason": f"Setup span too small ({span_pips:.1f} pips < {MIN_SETUP_PIPS})"})
            continue

        # ── Build Fibonacci ──────────────────────────────────────────────────
        direction = "SELL" if sweep_type == "BEAR" else "BUY"
        if direction == "SELL":
            fib_high, fib_low = sweep_price, bos_price
        else:
            fib_high, fib_low = bos_price, sweep_price

        # ── 1H HTF bias filter ───────────────────────────────────────────────
        bias_1h = get_htf_bias(htf_df, ts)
        if bias_1h != "NEUTRAL":
            if direction == "BUY"  and bias_1h != "BULL":
                filter_log.append({"date": date_str, "ts": ts,
                                    "reason": f"1H bias={bias_1h} blocks BUY"})
                continue
            if direction == "SELL" and bias_1h != "BEAR":
                filter_log.append({"date": date_str, "ts": ts,
                                    "reason": f"1H bias={bias_1h} blocks SELL"})
                continue

        # ── Daily HTF bias filter — macro trend must align ───────────────────
        if htf_daily_df is not None and not htf_daily_df.empty:
            bias_d = get_htf_bias(htf_daily_df, ts)
            if bias_d != "NEUTRAL":
                if direction == "BUY"  and bias_d != "BULL":
                    filter_log.append({"date": date_str, "ts": ts,
                                        "reason": f"Daily bias={bias_d} blocks BUY (counter-trend)"})
                    continue
                if direction == "SELL" and bias_d != "BEAR":
                    filter_log.append({"date": date_str, "ts": ts,
                                        "reason": f"Daily bias={bias_d} blocks SELL (counter-trend)"})
                    continue

        # ── OTE 0.618 only ───────────────────────────────────────────────────
        all_entries = calc_ote_entries(fib_high, fib_low, direction, symbol)
        entry_618   = next((e for e in all_entries
                            if abs(e["level"] - OTE_ENTRY_LVL) < 0.01), None)
        if entry_618 is None:
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
            entries     = [entry_618],
        ))
        used_dates.add(date_str)

    return signals, filter_log


# ── Trade Simulation with Breakeven ──────────────────────────────────────────

def simulate_v2(df: pd.DataFrame, signals: list, symbol: str) -> list[dict]:
    """Simulate trades — fixed SL and TP, no breakeven."""
    cfg    = SYMBOLS[symbol]
    pip    = cfg["pip"]
    trades = []

    for sig in signals:
        ed = sig.entries[0]   # always OTE 0.618 only
        entry_px = ed["entry"]
        sl_px    = ed["sl"]
        tp_px    = ed["tp"]
        sl_dist  = ed["sl_dist"]

        try:
            bos_loc = df.index.get_loc(sig.timestamp)
        except KeyError:
            bos_loc = df.index.searchsorted(sig.timestamp)
        if isinstance(bos_loc, slice):
            bos_loc = bos_loc.start

        result     = "OPEN"
        exit_px    = 0.0
        entry_time = exit_time = None
        entry_hit  = False

        for j in range(bos_loc + 1, min(bos_loc + FORWARD_SCAN, len(df))):
            bar = df.iloc[j]

            # Wait for entry to be hit
            if not entry_hit:
                if sig.direction == "SELL" and float(bar["high"]) >= entry_px:
                    entry_hit = True; entry_time = df.index[j]
                elif sig.direction == "BUY" and float(bar["low"]) <= entry_px:
                    entry_hit = True; entry_time = df.index[j]
                continue

            # Fixed SL / TP — no movement
            if sig.direction == "SELL":
                if float(bar["high"]) >= sl_px:
                    result = "LOSS"; exit_px = sl_px; exit_time = df.index[j]; break
                if float(bar["low"]) <= tp_px:
                    result = "WIN";  exit_px = tp_px; exit_time = df.index[j]; break
            else:
                if float(bar["low"]) <= sl_px:
                    result = "LOSS"; exit_px = sl_px; exit_time = df.index[j]; break
                if float(bar["high"]) >= tp_px:
                    result = "WIN";  exit_px = tp_px; exit_time = df.index[j]; break

        if result == "OPEN":
            continue

        sl_pips  = sl_dist / pip
        risk_usd = ACCOUNT_SIZE * (RISK_PCT / 100)
        lot      = round(risk_usd / (sl_pips * cfg["pip_val"]), 2)
        lot      = max(0.01, min(lot, 10.0))

        pnl = ((entry_px - exit_px) if sig.direction == "SELL"
               else (exit_px - entry_px))
        pnl = round(pnl / pip * cfg["pip_val"] * lot, 2)

        trades.append({
            "symbol":     symbol,
            "direction":  sig.direction,
            "ote_level":  OTE_ENTRY_LVL,
            "rr_target":  OTE_RR,
            "entry":      entry_px,
            "sl":         sl_px,
            "tp":         tp_px,
            "exit_price": exit_px,
            "result":     result,
            "pnl_usd":    pnl,
            "entry_time": entry_time,
            "exit_time":  exit_time,
            "asian_high": sig.asian_high,
            "asian_low":  sig.asian_low,
            "sweep_px":   sig.sweep_price,
            "bos_px":     sig.bos_price,
            "date":       sig.timestamp.date(),
        })

    return trades


# ── Charts ────────────────────────────────────────────────────────────────────

def signal_zoom_chart(df: pd.DataFrame, sig, trade: dict,
                      symbol: str, sig_num: int) -> go.Figure:
    """
    Zoomed-in chart for ONE signal.
    Window: previous day 22:00 UTC → BOS + 200 bars
    Clearly shows:  Asian box → AsH/AsL lines → sweep → BOS → OTE entry → SL/TP → trade result
    """
    direction = sig.direction
    col       = C["sell"] if direction == "SELL" else C["buy"]
    dir_label = "▼ SELL" if direction == "SELL" else "▲ BUY"

    # ── Zoom window: from Asian session start of that day ─────────────────────
    date_str  = str(sig.timestamp.date())
    win_start = pd.Timestamp(f"{date_str} 00:30", tz="UTC")  # before Asian forms
    try:
        bos_loc = df.index.get_loc(sig.timestamp)
    except KeyError:
        bos_loc = df.index.searchsorted(sig.timestamp)
    if isinstance(bos_loc, slice):
        bos_loc = bos_loc.start

    win_end_loc = min(bos_loc + 200, len(df) - 1)
    win_end     = df.index[win_end_loc]

    # If trade has exit time, extend window to show the full trade
    if trade and trade.get("exit_time"):
        win_end = max(win_end, trade["exit_time"] + pd.Timedelta(minutes=20))

    df_zoom = df[(df.index >= win_start) & (df.index <= win_end)].copy()
    if df_zoom.empty:
        df_zoom = df.iloc[max(0, bos_loc - 200): min(len(df), bos_loc + 200)].copy()

    shapes, annots = [], []

    # ── 1. Asian session shaded box ──────────────────────────────────────────
    asian_x0 = pd.Timestamp(f"{date_str} 01:00", tz="UTC")
    asian_x1 = pd.Timestamp(f"{date_str} 05:00", tz="UTC")

    shapes.append(dict(
        type="rect", xref="x", yref="y",
        x0=asian_x0, x1=asian_x1,
        y0=sig.asian_low, y1=sig.asian_high,
        fillcolor="rgba(100,149,237,0.18)",
        line=dict(color="#6495ED", width=2),
        layer="below",
    ))
    # Asian box label
    annots.append(dict(
        x=asian_x0 + (asian_x1 - asian_x0) / 2,
        y=(sig.asian_high + sig.asian_low) / 2,
        xref="x", yref="y",
        text="<b>ASIAN<br>SESSION</b>",
        showarrow=False,
        font=dict(color="#6495ED", size=10, family="monospace"),
        bgcolor="rgba(10,10,18,0.5)",
    ))

    # ── 2. AsH line — extends from Asian close all the way through chart ──────
    chart_end = df_zoom.index[-1]
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=asian_x1, x1=chart_end,
        y0=sig.asian_high, y1=sig.asian_high,
        line=dict(color="#6495ED", width=1.8, dash="dash"),
    ))
    annots.append(dict(
        x=asian_x1, y=sig.asian_high,
        xref="x", yref="y",
        text=f"<b>AsH {sig.asian_high:.5f}</b>",
        showarrow=False,
        font=dict(color="#6495ED", size=11, family="monospace"),
        xanchor="left",
        bgcolor="rgba(10,10,18,0.75)",
        bordercolor="#6495ED",
        borderwidth=1,
    ))

    # ── 3. AsL line — extends from Asian close all the way through chart ──────
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=asian_x1, x1=chart_end,
        y0=sig.asian_low, y1=sig.asian_low,
        line=dict(color="#6495ED", width=1.8, dash="dash"),
    ))
    annots.append(dict(
        x=asian_x1, y=sig.asian_low,
        xref="x", yref="y",
        text=f"<b>AsL {sig.asian_low:.5f}</b>",
        showarrow=False,
        font=dict(color="#6495ED", size=11, family="monospace"),
        xanchor="left",
        bgcolor="rgba(10,10,18,0.75)",
        bordercolor="#6495ED",
        borderwidth=1,
    ))

    # ── 4. Trade window shade (05:00–08:00 UTC) ───────────────────────────────
    tw_x0 = pd.Timestamp(f"{date_str} 05:00", tz="UTC")
    tw_x1 = pd.Timestamp(f"{date_str} 08:00", tz="UTC")
    shapes.append(dict(
        type="rect", xref="x", yref="y",
        x0=tw_x0, x1=tw_x1,
        y0=sig.asian_low * 0.9998,
        y1=sig.asian_high * 1.0002,
        fillcolor="rgba(255,215,0,0.04)",
        line=dict(color="rgba(255,215,0,0.25)", width=1, dash="dot"),
        layer="below",
    ))
    annots.append(dict(
        x=tw_x0, y=sig.asian_high,
        xref="x", yref="y",
        text="<b>TRADE WINDOW<br>05:00–08:00 UTC</b>",
        showarrow=False,
        font=dict(color="#FFD700", size=9, family="monospace"),
        xanchor="left", yanchor="bottom",
        bgcolor="rgba(10,10,18,0.6)",
    ))

    # ── 5. Sweep highlight ────────────────────────────────────────────────────
    annots.append(dict(
        x=sig.timestamp, y=sig.sweep_price,
        xref="x", yref="y",
        text=f"<b>SWEEP {dir_label}</b>",
        showarrow=True, arrowhead=2, arrowwidth=2,
        arrowcolor="#FF6B35",
        font=dict(color="#FF6B35", size=12, family="monospace"),
        ay=-45 if direction == "SELL" else 45, ax=0,
        bgcolor="rgba(10,10,18,0.8)",
        bordercolor="#FF6B35", borderwidth=1,
    ))
    # orange dot at sweep price
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=sig.timestamp - pd.Timedelta(minutes=4),
        x1=sig.timestamp + pd.Timedelta(minutes=4),
        y0=sig.sweep_price, y1=sig.sweep_price,
        line=dict(color="#FF6B35", width=3),
    ))

    # ── 6. BOS level ──────────────────────────────────────────────────────────
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=sig.timestamp, x1=chart_end,
        y0=sig.bos_price, y1=sig.bos_price,
        line=dict(color="#FFD700", width=1.5, dash="dot"),
    ))
    annots.append(dict(
        x=sig.timestamp, y=sig.bos_price,
        xref="x", yref="y",
        text=f"<b>BOS {sig.bos_price:.5f}</b>",
        showarrow=True, arrowhead=1, arrowwidth=1.5,
        arrowcolor="#FFD700",
        font=dict(color="#FFD700", size=11, family="monospace"),
        ay=30 if direction == "SELL" else -30, ax=0,
        bgcolor="rgba(10,10,18,0.8)",
        bordercolor="#FFD700", borderwidth=1,
    ))

    # ── 7. OTE zone (0.5–0.75 band) + 0.618 entry line ───────────────────────
    fib_rng = sig.fib_high - sig.fib_low
    ote_50  = sig.fib_high - 0.50  * fib_rng if direction == "SELL" else sig.fib_low + 0.50  * fib_rng
    ote_75  = sig.fib_high - 0.75  * fib_rng if direction == "SELL" else sig.fib_low + 0.75  * fib_rng

    shapes.append(dict(
        type="rect", xref="x", yref="y",
        x0=sig.timestamp, x1=chart_end,
        y0=min(ote_50, ote_75), y1=max(ote_50, ote_75),
        fillcolor="rgba(0,212,170,0.08)",
        line=dict(color="rgba(0,212,170,0.0)", width=0),
    ))

    if sig.entries:
        ed = sig.entries[0]
        # OTE 0.618 entry line (thick, colored)
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end,
            y0=ed["entry"], y1=ed["entry"],
            line=dict(color=col, width=2.5, dash="dashdot"),
        ))
        annots.append(dict(
            x=chart_end, y=ed["entry"],
            xref="x", yref="y",
            text=f" OTE 0.618 → 1:2R  {ed['entry']:.5f}",
            showarrow=False,
            font=dict(color=col, size=11, family="monospace"),
            xanchor="right",
            bgcolor="rgba(10,10,18,0.8)",
            bordercolor=col, borderwidth=1,
        ))
        # SL line
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end,
            y0=ed["sl"], y1=ed["sl"],
            line=dict(color="#FF1744", width=1.5, dash="dash"),
        ))
        annots.append(dict(
            x=chart_end, y=ed["sl"],
            xref="x", yref="y",
            text=f" SL {ed['sl']:.5f}",
            showarrow=False,
            font=dict(color="#FF1744", size=10, family="monospace"),
            xanchor="right",
            bgcolor="rgba(10,10,18,0.7)",
        ))
        # TP line
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end,
            y0=ed["tp"], y1=ed["tp"],
            line=dict(color="#00E676", width=1.5, dash="dot"),
        ))
        annots.append(dict(
            x=chart_end, y=ed["tp"],
            xref="x", yref="y",
            text=f" TP 1:2R  {ed['tp']:.5f}",
            showarrow=False,
            font=dict(color="#00E676", size=10, family="monospace"),
            xanchor="right",
            bgcolor="rgba(10,10,18,0.7)",
        ))

    # ── 8. Trade result box + black zone box ─────────────────────────────────
    if trade and trade.get("entry_time") and trade.get("exit_time"):
        tc     = "rgba(0,230,118,0.22)" if trade["result"] == "WIN" else "rgba(255,23,68,0.22)"
        bc     = C["win"] if trade["result"] == "WIN" else C["loss"]
        # Colored fill box (entry price to exit price)
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=trade["entry_time"], x1=trade["exit_time"],
            y0=min(trade["entry"], trade["exit_price"]),
            y1=max(trade["entry"], trade["exit_price"]),
            fillcolor=tc, line=dict(color=bc, width=1.5),
        ))
        # Black square border — full trade zone from SL to TP
        if sig.entries:
            ed_box = sig.entries[0]
            shapes.append(dict(
                type="rect", xref="x", yref="y",
                x0=trade["entry_time"], x1=trade["exit_time"],
                y0=min(ed_box["sl"], ed_box["tp"]),
                y1=max(ed_box["sl"], ed_box["tp"]),
                fillcolor="rgba(0,0,0,0)",
                line=dict(color="black", width=2.5),
                layer="above",
            ))
        mid_y = (trade["entry"] + trade["exit_price"]) / 2
        annots.append(dict(
            x=trade["exit_time"], y=mid_y,
            xref="x", yref="y",
            text=f"{'✓ WIN' if trade['result']=='WIN' else '✗ LOSS'}  ${trade['pnl_usd']:+.0f}",
            showarrow=False,
            font=dict(color=bc, size=12, family="monospace"),
            xanchor="left",
            bgcolor="rgba(10,10,18,0.8)",
            bordercolor=bc, borderwidth=1,
        ))

    # ── Build figure ──────────────────────────────────────────────────────────
    result_str = ""
    if trade:
        r_col = C["win"] if trade["result"] == "WIN" else C["loss"]
        result_str = (f" → <span style='color:{r_col}'>"
                      f"{'WIN' if trade['result']=='WIN' else 'LOSS'}"
                      f" ${trade['pnl_usd']:+.0f}</span>")

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_zoom.index,
        open=df_zoom["open"], high=df_zoom["high"],
        low=df_zoom["low"],  close=df_zoom["close"],
        name="2m (≈1m)",
        increasing=dict(line=dict(color=C["buy"]), fillcolor=C["buy"]),
        decreasing=dict(line=dict(color=C["sell"]), fillcolor=C["sell"]),
        whiskerwidth=0,
    ))

    fig.update_layout(
        shapes=shapes, annotations=annots,
        title=dict(
            text=(f"<b>{symbol}</b>  Setup #{sig_num}  ·  "
                  f"<b style='color:{col}'>{dir_label}</b>  ·  "
                  f"BOS @ {sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC"
                  f"{result_str}"),
            font=dict(size=14, color="white"),
        ),
        template="plotly_dark",
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        xaxis=dict(rangeslider=dict(visible=False), gridcolor=C["grid"], type="date"),
        yaxis=dict(gridcolor=C["grid"], tickformat=".5f", side="right"),
        height=560,
        margin=dict(l=10, r=180, t=60, b=30),
        showlegend=False,
    )
    return fig


def equity_curve_fig(all_trades: list) -> go.Figure:
    fig = go.Figure()
    for symbol in SYMBOLS:
        sym_t = sorted(
            [t for t in all_trades if t["symbol"] == symbol and t["exit_time"]],
            key=lambda x: x["exit_time"],
        )
        if not sym_t:
            continue
        bal, xs, ys = ACCOUNT_SIZE, [], []
        for t in sym_t:
            bal += t["pnl_usd"]
            xs.append(t["exit_time"]); ys.append(round(bal, 2))
        fig.add_trace(go.Scatter(x=xs, y=ys, name=symbol, mode="lines+markers",
                                 line=dict(width=2), marker=dict(size=4)))
    fig.add_hline(y=ACCOUNT_SIZE, line_dash="dot", line_color="#444",
                  annotation_text=f"Start ${ACCOUNT_SIZE:,.0f}")
    fig.update_layout(
        title="<b>Equity Curve</b>", yaxis_title="Balance ($)",
        template="plotly_dark", paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        height=340, margin=dict(l=60, r=40, t=50, b=40),
    )
    return fig


def monthly_pnl_fig(all_trades: list) -> go.Figure:
    pnl: dict = {}
    for t in all_trades:
        if not t["exit_time"]:
            continue
        key = t["exit_time"].strftime("%b %Y")
        pnl[key] = round(pnl.get(key, 0) + t["pnl_usd"], 2)
    months = list(pnl.keys())
    vals   = list(pnl.values())
    fig = go.Figure(go.Bar(
        x=months, y=vals,
        marker_color=[C["win"] if v >= 0 else C["loss"] for v in vals],
        text=[f"${v:+.0f}" for v in vals],
        textposition="outside",
    ))
    fig.update_layout(
        title="<b>Monthly P&L</b>", yaxis_title="P&L ($)",
        template="plotly_dark", paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        height=300, margin=dict(l=60, r=40, t=50, b=60),
        xaxis=dict(tickangle=-30),
    )
    return fig


def filter_breakdown_fig(all_filter_logs: list) -> go.Figure:
    reasons: dict = {}
    for entry in all_filter_logs:
        r = entry["reason"].split("(")[0].strip()
        reasons[r] = reasons.get(r, 0) + 1
    if not reasons:
        return go.Figure()
    items  = sorted(reasons.items(), key=lambda x: -x[1])
    labels = [x[0] for x in items]
    counts = [x[1] for x in items]
    fig = go.Figure(go.Bar(
        y=labels, x=counts, orientation="h",
        marker_color="#6495ED",
        text=counts, textposition="outside",
    ))
    fig.update_layout(
        title="<b>Setups Filtered Out — By Reason</b>",
        xaxis_title="Count",
        template="plotly_dark", paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        height=max(280, len(labels) * 45 + 80),
        margin=dict(l=240, r=60, t=50, b=40),
    )
    return fig


def summary_table_fig(all_trades: list, sym_signals: dict) -> go.Figure:
    rows = []
    for symbol in SYMBOLS:
        st   = [t for t in all_trades if t["symbol"] == symbol]
        wins = sum(1 for t in st if t["result"] == "WIN")
        tot  = len(st)
        net  = round(sum(t["pnl_usd"] for t in st), 2)
        wr   = round(wins / tot * 100, 1) if tot else 0
        rows.append([symbol, sym_signals.get(symbol, 0), tot, wins,
                     tot - wins, f"{wr}%", f"${net:+.2f}"])
    wins_a = sum(1 for t in all_trades if t["result"] == "WIN")
    tot_a  = len(all_trades)
    net_a  = round(sum(t["pnl_usd"] for t in all_trades), 2)
    wr_a   = round(wins_a / tot_a * 100, 1) if tot_a else 0
    rows.append(["TOTAL", sum(sym_signals.values()), tot_a,
                 wins_a, tot_a - wins_a, f"{wr_a}%", f"${net_a:+.2f}"])

    headers = ["Pair", "Setups", "Trades", "Wins", "Losses", "Win Rate", "Net P&L"]
    fig = go.Figure(go.Table(
        header=dict(values=[f"<b>{h}</b>" for h in headers],
                    fill_color="#13131f", font=dict(color="white", size=13),
                    align="center", height=36),
        cells=dict(values=list(zip(*rows)),
                   fill_color=[["#0d0d1a"] * (len(rows)-1) + ["#131320"]],
                   font=dict(color=[["white"] * (len(rows)-1) + ["#FFD700"]], size=12),
                   align="center", height=30),
    ))
    fig.update_layout(
        title="<b>Phase-404 v2.0 — 2-Month Backtest Summary</b>",
        template="plotly_dark", paper_bgcolor=C["bg"],
        height=220 + len(rows) * 10,
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def trade_log_fig(all_trades: list) -> go.Figure:
    if not all_trades:
        return go.Figure()
    sorted_t = sorted(all_trades, key=lambda x: x["entry_time"] or datetime.min)
    rows, running = [], ACCOUNT_SIZE
    for i, t in enumerate(sorted_t, 1):
        running += t["pnl_usd"]
        rows.append([
            i, t["symbol"], t["direction"],
            t["entry_time"].strftime("%m-%d %H:%M") if t["entry_time"] else "—",
            t["exit_time"].strftime("%m-%d %H:%M") if t["exit_time"] else "—",
            f"{t['entry']:.5f}", f"{t['sl']:.5f}", f"{t['tp']:.5f}",
            f"{t['exit_price']:.5f}",
            "✓ WIN" if t["result"] == "WIN" else "✗ LOSS",
            f"${t['pnl_usd']:+.2f}", f"${running:,.2f}",
        ])
    headers = ["#", "Pair", "Dir", "Entry Time", "Exit Time",
               "Entry Px", "SL", "TP", "Exit Px", "Result", "P&L", "Balance"]
    cell_vals = list(zip(*rows))
    result_i = headers.index("Result")
    pnl_i    = headers.index("P&L")
    res_cols = [C["win"] if "WIN" in str(v) else C["loss"] for v in cell_vals[result_i]]
    pnl_cols = [C["win"] if float(str(v).replace("$","").replace("+","")) >= 0 else C["loss"]
                for v in cell_vals[pnl_i]]
    font_cols = []
    for i in range(len(headers)):
        if i == result_i:   font_cols.append(res_cols)
        elif i == pnl_i:    font_cols.append(pnl_cols)
        else:               font_cols.append(["#ddd"] * len(rows))

    fig = go.Figure(go.Table(
        header=dict(values=[f"<b>{h}</b>" for h in headers],
                    fill_color="#13131f", font=dict(color="white", size=11),
                    align="center", height=32),
        cells=dict(values=cell_vals,
                   fill_color=[["#0d0d1a", "#0e0e1a"] * (len(rows)//2 + 1)][:len(rows)],
                   font=dict(color=font_cols, size=10),
                   align="center", height=26),
    ))
    fig.update_layout(
        title="<b>Full Trade Log</b>", template="plotly_dark",
        paper_bgcolor=C["bg"],
        height=min(180 + len(rows) * 27, 1400),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# ── HTML Builder ──────────────────────────────────────────────────────────────

STYLE = """<style>
*{box-sizing:border-box}
body{background:#0a0a12;color:#ddd;font-family:'Segoe UI',sans-serif;margin:0;padding:24px 32px}
h1{color:#00D4AA;border-bottom:2px solid #00D4AA;padding-bottom:10px}
h2{color:#6495ED;margin-top:44px;font-size:19px}
h3{color:#FFD700;margin:4px 0 14px;font-size:14px;font-weight:normal}
.rule-box{background:#0e0e1a;border:1px solid #6495ED;border-radius:10px;
          padding:18px 24px;margin-bottom:28px;font-size:14px;line-height:2}
.tag{background:#1a1a3e;border-radius:4px;padding:2px 9px;color:#FFD700;
     margin:0 4px;font-family:monospace}
.stat-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:28px}
.stat-card{background:#0e0e1a;border:1px solid #1a1a3e;border-radius:10px;
           padding:12px 18px;min-width:130px;flex:1}
.stat-card .label{color:#666;font-size:11px;margin-bottom:3px}
.stat-card .value{font-size:21px;font-weight:bold;font-family:monospace}
.win{color:#00E676}.loss{color:#FF1744}
.section{margin-bottom:18px}
.note{background:#131320;border-left:3px solid #FFD700;
      padding:10px 16px;margin-bottom:20px;border-radius:0 8px 8px 0;
      font-size:13px;color:#aaa}
.filter-list{background:#0e0e1a;border:1px solid #1a1a3e;border-radius:8px;
             padding:14px 20px;font-family:monospace;font-size:12px;line-height:1.9}
</style>"""


def build_html(sym_results: dict, all_filter_logs: list) -> str:
    all_trades = [t for d in sym_results.values() for t in d["trades"]]
    total   = len(all_trades)
    wins    = sum(1 for t in all_trades if t["result"] == "WIN")
    net     = round(sum(t["pnl_usd"] for t in all_trades), 2)
    wr      = round(wins / total * 100, 1) if total else 0
    all_sigs= sum(len(d["signals"]) for d in sym_results.values())

    times   = [t["entry_time"] for t in all_trades if t["entry_time"]]
    d_from  = min(times).strftime("%Y-%m-%d") if times else "N/A"
    d_to    = max(times).strftime("%Y-%m-%d") if times else "N/A"

    sym_signals = {s: len(d["signals"]) for s, d in sym_results.items()}

    parts = [f"""<!DOCTYPE html><html lang="en">
<head><meta charset="utf-8">
<title>Phase-404 v2.1 | 2-Month Backtest</title>{STYLE}</head><body>
<h1>Phase-404 v2.1 — 2-Month Backtest · Signal Sketches</h1>
<div class="rule-box">
  <b style="color:#00D4AA;font-size:15px;">Strategy v2.1</b><br>
  <i>"Trade the retest after a liquidity sweep, in the direction of the trend."</i><br>
  Mark Asian H/L (01:00–05:00 UTC) →
  <span class="tag">Sweep 05:00–08:00 UTC</span> →
  BOS on M1 → <span class="tag">OTE 0.618 → 1:2R</span> ·
  SL per-pair (EUR=10p · GBP=12p · USDJPY=15p · GBPJPY=18p) · Fixed SL/TP<br>
  Filters: 1H + Daily EMA50 trend aligned · BOS body ≥40% · Sweep wick ≥8% · Span ≥7p
</div>
<div class="note">
  ⚡ <b>Data:</b> 2-minute candles (yfinance 60-day max) ·
  Covers <b>{d_from}</b> to <b>{d_to}</b> · Weekends auto-excluded
</div>
<div class="stat-row">
  <div class="stat-card"><div class="label">Date Range</div>
    <div class="value" style="font-size:13px">{d_from}<br>→ {d_to}</div></div>
  <div class="stat-card"><div class="label">Setups Passed</div>
    <div class="value">{all_sigs}</div></div>
  <div class="stat-card"><div class="label">Total Trades</div>
    <div class="value">{total}</div></div>
  <div class="stat-card"><div class="label">Win Rate</div>
    <div class="value {'win' if wr>=50 else 'loss'}">{wr}%</div></div>
  <div class="stat-card"><div class="label">Wins / Losses</div>
    <div class="value"><span class="win">{wins}W</span> / <span class="loss">{total-wins}L</span></div></div>
  <div class="stat-card"><div class="label">Net P&L</div>
    <div class="value {'win' if net>=0 else 'loss'}">${net:+.2f}</div></div>
  <div class="stat-card"><div class="label">Filtered Out</div>
    <div class="value" style="font-size:16px;color:#888">{len(all_filter_logs)}</div></div>
</div>
"""]

    first_plotly = True

    def add_fig(fig):
        nonlocal first_plotly
        inc = "cdn" if first_plotly else False
        first_plotly = False
        return f'<div class="section">{fig.to_html(full_html=False, include_plotlyjs=inc)}</div>'

    # Summary charts
    parts.append("<h2>Performance Summary</h2>")
    parts.append(add_fig(summary_table_fig(all_trades, sym_signals)))
    parts.append(add_fig(equity_curve_fig(all_trades)))
    parts.append(add_fig(monthly_pnl_fig(all_trades)))
    parts.append(add_fig(filter_breakdown_fig(all_filter_logs)))

    # Per-symbol, per-signal zoomed charts
    for symbol, data in sym_results.items():
        df      = data["df"]
        signals = data["signals"]
        trades  = data["trades"]
        sym_w   = sum(1 for t in trades if t["result"] == "WIN")
        sym_tot = len(trades)
        sym_net = round(sum(t["pnl_usd"] for t in trades), 2)
        sym_wr  = round(sym_w / sym_tot * 100, 1) if sym_tot else 0

        if not signals:
            continue

        parts.append(f"""<h2>{symbol} — Signal-by-Signal Breakdown</h2>
<h3>{len(signals)} setups · {sym_tot} trades ·
<span class="{'win' if sym_wr>=50 else 'loss'}">WR {sym_wr}%</span> ·
<span class="{'win' if sym_net>=0 else 'loss'}">Net ${sym_net:+.2f}</span></h3>""")

        # Match each signal to its trade
        for sig_num, sig in enumerate(signals, 1):
            matched_trade = next(
                (t for t in trades
                 if t["direction"] == sig.direction
                 and t.get("entry_time")
                 and t["entry_time"] >= sig.timestamp),
                None,
            )
            parts.append(add_fig(
                signal_zoom_chart(df, sig, matched_trade, symbol, sig_num)
            ))

    # Trade log
    parts.append("<h2>Full Trade Log</h2>")
    parts.append(add_fig(trade_log_fig(all_trades)))

    # Filtered setups log
    if all_filter_logs:
        parts.append("<h2>Filtered-Out Setups Log</h2>")
        parts.append('<div class="filter-list">')
        for entry in all_filter_logs[:100]:
            parts.append(
                f"<span style='color:#888'>{entry['ts'].strftime('%Y-%m-%d %H:%M')}</span>  "
                f"<span style='color:#6495ED'>{entry.get('symbol','')}</span>  "
                f"→ {entry['reason']}<br>"
            )
        if len(all_filter_logs) > 100:
            parts.append(f"<br><i>... {len(all_filter_logs)-100} more filtered entries not shown</i>")
        parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 65)
    print("  Phase-404 v2.2 | 2-Month Backtest (2m data, 4 pairs, London only)")
    print("=" * 65)

    sym_results    = {}
    all_filter_logs = []

    for symbol in SYMBOLS:
        print(f"\n[{symbol}]")
        df          = fetch_2m(symbol)
        htf_df      = fetch_1h_htf(symbol)
        htf_daily   = fetch_daily_htf(symbol)

        if df.empty:
            print("  No data — skipping")
            continue

        print(f"  1H HTF : {len(htf_df)} bars loaded" if not htf_df.empty
              else "  1H HTF : no data — bias filter disabled")
        print(f"  Daily  : {len(htf_daily)} bars loaded" if not htf_daily.empty
              else "  Daily  : no data — macro filter disabled")

        print(f"  Generating v2.2 signals...", end=" ", flush=True)
        signals, flog = generate_signals_v2(df, symbol, htf_df, htf_daily)
        for f in flog:
            f["symbol"] = symbol
        all_filter_logs.extend(flog)
        print(f"{len(signals)} setups passed  |  {len(flog)} filtered out")

        for sig in signals:
            print(f"    → {sig.direction:4s}  {sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC  "
                  f"Sweep@{sig.sweep_price:.5f}  BOS@{sig.bos_price:.5f}  "
                  f"OTE@{sig.entries[0]['entry']:.5f}")

        if not signals:
            sym_results[symbol] = {"df": df, "signals": [], "trades": []}
            continue

        print(f"  Simulating trades...", end=" ", flush=True)
        trades = simulate_v2(df, signals, symbol)
        wins   = sum(1 for t in trades if t["result"] == "WIN")
        total  = len(trades)
        print(f"{total} trades | WR={round(wins/total*100,1) if total else 0}%")

        for t in trades:
            r = "✓" if t["result"] == "WIN" else "✗"
            print(f"    {r} {t['direction']:4s}  "
                  f"{t['entry_time'].strftime('%m-%d %H:%M') if t['entry_time'] else '?'}  "
                  f"P&L ${t['pnl_usd']:+.2f}")

        sym_results[symbol] = {"df": df, "signals": signals, "trades": trades}

    all_t  = [t for d in sym_results.values() for t in d["trades"]]
    wins   = sum(1 for t in all_t if t["result"] == "WIN")
    total  = len(all_t)
    net    = round(sum(t["pnl_usd"] for t in all_t), 2)
    wr     = round(wins / total * 100, 1) if total else 0

    print(f"\n{'='*65}")
    print(f"  DATA RANGE    : {sym_results[list(sym_results.keys())[0]]['df'].index[0].date() if sym_results else 'N/A'}"
          f" → {sym_results[list(sym_results.keys())[0]]['df'].index[-1].date() if sym_results else 'N/A'}")
    print(f"  SETUPS PASSED : {sum(len(d['signals']) for d in sym_results.values())}")
    print(f"  FILTERED OUT  : {len(all_filter_logs)}")
    print(f"  TOTAL TRADES  : {total}")
    print(f"  WIN RATE      : {wr}%")
    print(f"  NET P&L       : ${net:+.2f}")
    print(f"{'='*65}")

    if not any(d["trades"] for d in sym_results.values()):
        print("\nNo closed trades. Try widening filters.")
        return

    print("\n[Report] Building 2-month HTML report...")
    html     = build_html(sym_results, all_filter_logs)
    out_file = OUT_DIR / "phase404_2month_report.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"[Report] Saved → {out_file}")

    import webbrowser
    webbrowser.open(str(out_file))


if __name__ == "__main__":
    run()
