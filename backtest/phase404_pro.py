"""
Phase-404 Professional Backtest Engine v1.0
============================================
Philosophy: "Trade the retest after a liquidity sweep, in the direction of the trend."

Architecture:
  • Data:    Redis-backed OHLCV store (2m candles, accumulates over runs)
  • Config:  Per-pair strategy parameters (pair_config.py)
  • Signals: Per-pair tuned sweep/BOS/HTF filters
  • Report:  HTML with per-signal charts + statistical validity indicator

Statistical validity: Each pair needs ≥ 25 trades before results are trustable.
Target win rate: 70% per pair.

Run: python -m backtest.phase404_pro
     python -m backtest.phase404_pro --update   (refresh data first)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

from backtest.pair_config import PAIR_CONFIGS, PairConfig
from backtest.data_store  import (load, update_1m, update_htf,
                                   status_report, count, date_range)
from backtest.phase404_signals import (
    get_asian_ranges, detect_sweep_rolling, detect_bos,
    AsianRange, Signal,
)

ACCOUNT_SIZE = 10_000.0
RISK_PCT     = 1.0
OUT_DIR      = Path(__file__).parent.parent / "data" / "phase404"
OUT_DIR.mkdir(parents=True, exist_ok=True)

C = {
    "bg": "#0a0a12", "bg2": "#0e0e1a", "grid": "#1a1a28",
    "asian": "rgba(100,149,237,0.14)", "asian_l": "#6495ED",
    "sweep": "#FF6B35", "bos": "#FFD700",
    "sell": "#FF4444", "buy": "#00CC66",
    "win": "#00E676", "loss": "#FF1744",
}


# ── HTF EMA bias ──────────────────────────────────────────────────────────────

def _compute_ema(df: pd.DataFrame, period: int) -> pd.DataFrame:
    df = df.copy()
    df["ema"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def get_bias(htf_df: pd.DataFrame, ts: pd.Timestamp) -> str:
    """Return BULL / BEAR / NEUTRAL based on close vs EMA at ts."""
    if htf_df.empty or "ema" not in htf_df.columns:
        return "NEUTRAL"
    idx = htf_df.index.searchsorted(ts) - 1
    if idx < 0:
        return "NEUTRAL"
    idx = min(idx, len(htf_df) - 1)
    row = htf_df.iloc[idx]
    if pd.isna(row["ema"]):
        return "NEUTRAL"
    if float(row["close"]) > float(row["ema"]):
        return "BULL"
    if float(row["close"]) < float(row["ema"]):
        return "BEAR"
    return "NEUTRAL"


def session_bias(daily_df: pd.DataFrame, ts: pd.Timestamp,
                 days: int = 2) -> str:
    """
    Returns 'BULL', 'BEAR', or 'NEUTRAL' based on the last N completed daily candles.
    Both closes bullish (close > open) → BULL.
    Both closes bearish (close < open) → BEAR.
    Mixed → NEUTRAL (allow both directions).
    No EMA lag — reacts to recent price action directly.
    """
    if daily_df.empty or "open" not in daily_df.columns:
        return "NEUTRAL"
    past = daily_df[daily_df.index < ts].tail(days)
    if len(past) < days:
        return "NEUTRAL"
    bulls = sum(1 for _, r in past.iterrows() if float(r["close"]) > float(r["open"]))
    bears = days - bulls
    if bulls == days:
        return "BULL"
    if bears == days:
        return "BEAR"
    return "NEUTRAL"


def fetch_daily(cfg: PairConfig) -> pd.DataFrame:
    """Fetch daily OHLC from Redis or yfinance. Keeps open+close for session bias."""
    df = load(cfg.symbol, "1d")
    if df.empty:
        df = yf.download(cfg.ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "close"]].dropna().sort_index()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
    if df.empty:
        return pd.DataFrame()
    return df


# ── OTE entry calculation (per-pair SL) ──────────────────────────────────────

def calc_ote(fib_high: float, fib_low: float,
             direction: str, cfg: PairConfig) -> dict | None:
    """Calculate OTE 0.618 entry with per-pair SL pips."""
    rng = fib_high - fib_low
    if rng <= 0:
        return None
    buf   = cfg.sl_pips * cfg.pip
    level = cfg.ote_level

    if direction == "SELL":
        entry   = round(fib_high - level * rng, 6)
        sl      = round(fib_high + buf, 6)
        sl_dist = abs(sl - entry)
        tp      = round(entry - cfg.rr * sl_dist, 6)
    else:
        entry   = round(fib_low + level * rng, 6)
        sl      = round(fib_low - buf, 6)
        sl_dist = abs(entry - sl)
        tp      = round(entry + cfg.rr * sl_dist, 6)

    if sl_dist <= 0:
        return None

    return {"entry": entry, "sl": sl, "tp": tp,
            "sl_dist": round(sl_dist, 6), "level": level, "rr": cfg.rr}


# ── Signal Generation (per-pair config) ──────────────────────────────────────

def generate_signals_pro(df: pd.DataFrame, cfg: PairConfig,
                         daily_df: pd.DataFrame) -> tuple[list[Signal], list[dict]]:
    """
    Phase-404 signal generator using PairConfig.
    All filter thresholds are pair-specific — no global constants.
    Returns (signals, filter_log).
    """
    if df.empty or len(df) < cfg.bos_lookback + cfg.sweep_lookback:
        return [], []

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    min_range  = cfg.min_asian_range_pips * cfg.pip
    asian_ranges = get_asian_ranges(df)

    signals:    list[Signal] = []
    filter_log: list[dict]   = []
    used_dates: set[str]     = set()

    start_i = cfg.bos_lookback + cfg.sweep_lookback

    for i in range(start_i, len(df)):
        ts   = df.index[i]
        hour = ts.hour

        # ── Trade window gate ────────────────────────────────────────────────
        if not (cfg.kill_start <= hour < cfg.kill_end):
            continue

        date_str = str(ts.date())
        if date_str in used_dates:
            continue

        ar = asian_ranges.get(date_str)
        if ar is None:
            continue

        # ── Minimum Asian range ──────────────────────────────────────────────
        ar_size = ar.high - ar.low
        if ar_size < min_range:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": f"Asian range {ar_size/cfg.pip:.1f}p < {cfg.min_asian_range_pips}p"})
            used_dates.add(date_str)   # one check per day
            continue

        # ── Rolling sweep detection ──────────────────────────────────────────
        sweep_type = detect_sweep_rolling(df, i, ar,
                                          lookback=cfg.sweep_lookback,
                                          min_wick_pct=cfg.min_wick_pct)
        if sweep_type is None:
            continue   # keep scanning same day — sweep may arrive later

        window      = df.iloc[i - cfg.sweep_lookback: i + 1]
        sweep_price = float(window["high"].max()) if sweep_type == "BEAR" \
                      else float(window["low"].min())

        # ── Absolute sweep wick pip filter ───────────────────────────────────
        wick_pips = (abs(sweep_price - ar.high) if sweep_type == "BEAR"
                     else abs(ar.low - sweep_price)) / cfg.pip
        if wick_pips < cfg.min_wick_pips:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": f"Wick {wick_pips:.1f}p < {cfg.min_wick_pips}p (abs)"})
            used_dates.add(date_str); continue

        # ── BOS detection ────────────────────────────────────────────────────
        bos = detect_bos(df, i, sweep_type,
                         bos_lookback=cfg.bos_lookback,
                         bos_scan_forward=cfg.bos_scan_forward)
        if bos is None:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": "No BOS found"})
            used_dates.add(date_str)
            continue

        bos_idx, bos_price = bos
        bos_candle = df.iloc[bos_idx]

        # ── BOS pip strength ─────────────────────────────────────────────────
        swing_pre = df.iloc[max(0, i - cfg.bos_lookback): i]
        if sweep_type == "BEAR":
            swing_ref  = float(swing_pre["low"].min())
            bos_excess = (swing_ref - float(bos_candle["close"])) / cfg.pip
        else:
            swing_ref  = float(swing_pre["high"].max())
            bos_excess = (float(bos_candle["close"]) - swing_ref) / cfg.pip

        if bos_excess < cfg.bos_strength_pips:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": f"BOS strength {bos_excess:.1f}p < {cfg.bos_strength_pips}p"})
            used_dates.add(date_str)
            continue

        # ── Minimum setup span ───────────────────────────────────────────────
        span_pips = abs(sweep_price - bos_price) / cfg.pip
        if span_pips < cfg.min_setup_pips:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": f"Setup span {span_pips:.1f}p < {cfg.min_setup_pips}p"})
            used_dates.add(date_str)
            continue

        # ── Build direction + Fib ────────────────────────────────────────────
        direction = "SELL" if sweep_type == "BEAR" else "BUY"
        if direction == "SELL":
            fib_high, fib_low = sweep_price, bos_price
        else:
            fib_high, fib_low = bos_price, sweep_price

        # ── Minimum fib range filter ─────────────────────────────────────────
        fib_range_pips = (fib_high - fib_low) / cfg.pip
        if fib_range_pips < cfg.min_fib_range_pips:
            filter_log.append({"date": date_str, "ts": ts,
                "reason": f"Fib range {fib_range_pips:.1f}p < {cfg.min_fib_range_pips}p"})
            used_dates.add(date_str); continue

        # ── Session momentum bias ─────────────────────────────────────────────
        if cfg.use_session_bias and not daily_df.empty:
            bias = session_bias(daily_df, ts, cfg.session_bias_days)
            if bias != "NEUTRAL":
                if direction == "BUY"  and bias != "BULL":
                    filter_log.append({"date": date_str, "ts": ts,
                        "reason": f"Session bias={bias} blocks BUY"})
                    used_dates.add(date_str); continue
                if direction == "SELL" and bias != "BEAR":
                    filter_log.append({"date": date_str, "ts": ts,
                        "reason": f"Session bias={bias} blocks SELL"})
                    used_dates.add(date_str); continue

        # ── OTE 0.618 entry ──────────────────────────────────────────────────
        entry_data = calc_ote(fib_high, fib_low, direction, cfg)
        if entry_data is None:
            continue

        signals.append(Signal(
            timestamp   = df.index[bos_idx],
            direction   = direction,
            sweep_price = round(sweep_price, 6),
            bos_price   = round(bos_price, 6),
            fib_high    = round(fib_high, 6),
            fib_low     = round(fib_low, 6),
            asian_high  = ar.high,
            asian_low   = ar.low,
            entries     = [entry_data],
        ))
        used_dates.add(date_str)

    return signals, filter_log


# ── Trade Simulation ──────────────────────────────────────────────────────────

def simulate_pro(df: pd.DataFrame, signals: list[Signal],
                 cfg: PairConfig) -> list[dict]:
    """Fixed SL/TP simulation — no breakeven. One entry per signal (OTE 0.618)."""
    trades = []

    for sig in signals:
        ed       = sig.entries[0]
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

        for j in range(bos_loc + 1, min(bos_loc + cfg.forward_scan, len(df))):
            bar = df.iloc[j]

            if not entry_hit:
                if sig.direction == "SELL" and float(bar["high"]) >= entry_px:
                    entry_hit = True; entry_time = df.index[j]
                elif sig.direction == "BUY" and float(bar["low"]) <= entry_px:
                    entry_hit = True; entry_time = df.index[j]
                continue

            if sig.direction == "SELL":
                if float(bar["high"]) >= sl_px:
                    result = "LOSS"; exit_px = sl_px; exit_time = df.index[j]; break
                if float(bar["low"])  <= tp_px:
                    result = "WIN";  exit_px = tp_px; exit_time = df.index[j]; break
            else:
                if float(bar["low"])  <= sl_px:
                    result = "LOSS"; exit_px = sl_px; exit_time = df.index[j]; break
                if float(bar["high"]) >= tp_px:
                    result = "WIN";  exit_px = tp_px; exit_time = df.index[j]; break

        if result == "OPEN":
            continue

        sl_pips  = sl_dist / cfg.pip
        risk_usd = ACCOUNT_SIZE * (RISK_PCT / 100)
        lot      = round(risk_usd / (sl_pips * cfg.pip_val), 2)
        lot      = max(0.01, min(lot, 10.0))

        pnl = ((entry_px - exit_px) if sig.direction == "SELL"
               else (exit_px - entry_px))
        pnl = round(pnl / cfg.pip * cfg.pip_val * lot, 2)

        trades.append({
            "symbol":     cfg.symbol,
            "direction":  sig.direction,
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
            "sl_pips":    round(sl_pips, 1),
        })

    return trades


# ── Per-signal zoomed chart ───────────────────────────────────────────────────

def signal_zoom_chart(df: pd.DataFrame, sig: Signal, trade: dict,
                      cfg: PairConfig, sig_num: int) -> go.Figure:
    direction = sig.direction
    col       = C["sell"] if direction == "SELL" else C["buy"]
    dir_label = "▼ SELL" if direction == "SELL" else "▲ BUY"
    fmt       = f".{5 if cfg.pip == 0.0001 else 3}f"

    date_str  = str(sig.timestamp.date())
    win_start = pd.Timestamp(f"{date_str} 00:30", tz="UTC")

    try:
        bos_loc = df.index.get_loc(sig.timestamp)
    except KeyError:
        bos_loc = df.index.searchsorted(sig.timestamp)
    if isinstance(bos_loc, slice):
        bos_loc = bos_loc.start

    win_end_loc = min(bos_loc + 200, len(df) - 1)
    win_end     = df.index[win_end_loc]
    if trade and trade.get("exit_time"):
        win_end = max(win_end, trade["exit_time"] + pd.Timedelta(minutes=20))

    df_zoom = df[(df.index >= win_start) & (df.index <= win_end)].copy()
    if df_zoom.empty:
        df_zoom = df.iloc[max(0, bos_loc-200): min(len(df), bos_loc+200)].copy()

    shapes, annots = [], []
    chart_end = df_zoom.index[-1]

    # ── 1. Asian session box ─────────────────────────────────────────────────
    asian_x0 = pd.Timestamp(f"{date_str} 01:00", tz="UTC")
    asian_x1 = pd.Timestamp(f"{date_str} 05:00", tz="UTC")
    shapes.append(dict(type="rect", xref="x", yref="y",
        x0=asian_x0, x1=asian_x1, y0=sig.asian_low, y1=sig.asian_high,
        fillcolor="rgba(100,149,237,0.18)", line=dict(color="#6495ED", width=2),
        layer="below"))
    annots.append(dict(
        x=asian_x0 + (asian_x1 - asian_x0) / 2,
        y=(sig.asian_high + sig.asian_low) / 2,
        xref="x", yref="y", text="<b>ASIAN</b>", showarrow=False,
        font=dict(color="#6495ED", size=10, family="monospace"),
        bgcolor="rgba(10,10,18,0.5)"))

    # ── 2. AsH line ──────────────────────────────────────────────────────────
    shapes.append(dict(type="line", xref="x", yref="y",
        x0=asian_x1, x1=chart_end, y0=sig.asian_high, y1=sig.asian_high,
        line=dict(color="#6495ED", width=1.8, dash="dash")))
    annots.append(dict(x=asian_x1, y=sig.asian_high, xref="x", yref="y",
        text=f"<b>AsH {sig.asian_high:{fmt}}</b>", showarrow=False,
        font=dict(color="#6495ED", size=10, family="monospace"), xanchor="left",
        bgcolor="rgba(10,10,18,0.75)", bordercolor="#6495ED", borderwidth=1))

    # ── 3. AsL line ──────────────────────────────────────────────────────────
    shapes.append(dict(type="line", xref="x", yref="y",
        x0=asian_x1, x1=chart_end, y0=sig.asian_low, y1=sig.asian_low,
        line=dict(color="#6495ED", width=1.8, dash="dash")))
    annots.append(dict(x=asian_x1, y=sig.asian_low, xref="x", yref="y",
        text=f"<b>AsL {sig.asian_low:{fmt}}</b>", showarrow=False,
        font=dict(color="#6495ED", size=10, family="monospace"), xanchor="left",
        bgcolor="rgba(10,10,18,0.75)", bordercolor="#6495ED", borderwidth=1))

    # ── 4. Trade window shade ────────────────────────────────────────────────
    tw_x0 = pd.Timestamp(f"{date_str} {cfg.kill_start:02d}:00", tz="UTC")
    tw_x1 = pd.Timestamp(f"{date_str} {cfg.kill_end:02d}:00", tz="UTC")
    shapes.append(dict(type="rect", xref="x", yref="y",
        x0=tw_x0, x1=tw_x1,
        y0=sig.asian_low * 0.9998, y1=sig.asian_high * 1.0002,
        fillcolor="rgba(255,215,0,0.04)",
        line=dict(color="rgba(255,215,0,0.25)", width=1, dash="dot"),
        layer="below"))
    annots.append(dict(x=tw_x0, y=sig.asian_high, xref="x", yref="y",
        text=f"<b>WINDOW {cfg.kill_start:02d}:00–{cfg.kill_end:02d}:00</b>",
        showarrow=False, font=dict(color="#FFD700", size=9, family="monospace"),
        xanchor="left", yanchor="bottom", bgcolor="rgba(10,10,18,0.6)"))

    # ── 5. Sweep annotation ──────────────────────────────────────────────────
    annots.append(dict(x=sig.timestamp, y=sig.sweep_price, xref="x", yref="y",
        text=f"<b>SWEEP</b>", showarrow=True, arrowhead=2, arrowwidth=2,
        arrowcolor="#FF6B35", font=dict(color="#FF6B35", size=11, family="monospace"),
        ay=-40 if direction == "SELL" else 40, ax=0,
        bgcolor="rgba(10,10,18,0.8)", bordercolor="#FF6B35", borderwidth=1))
    shapes.append(dict(type="line", xref="x", yref="y",
        x0=sig.timestamp - pd.Timedelta(minutes=4),
        x1=sig.timestamp + pd.Timedelta(minutes=4),
        y0=sig.sweep_price, y1=sig.sweep_price,
        line=dict(color="#FF6B35", width=3)))

    # ── 6. BOS level ─────────────────────────────────────────────────────────
    shapes.append(dict(type="line", xref="x", yref="y",
        x0=sig.timestamp, x1=chart_end, y0=sig.bos_price, y1=sig.bos_price,
        line=dict(color="#FFD700", width=1.5, dash="dot")))
    annots.append(dict(x=sig.timestamp, y=sig.bos_price, xref="x", yref="y",
        text=f"<b>BOS {sig.bos_price:{fmt}}</b>",
        showarrow=True, arrowhead=1, arrowwidth=1.5, arrowcolor="#FFD700",
        font=dict(color="#FFD700", size=10, family="monospace"),
        ay=25 if direction == "SELL" else -25, ax=0,
        bgcolor="rgba(10,10,18,0.8)", bordercolor="#FFD700", borderwidth=1))

    # ── 7. OTE entry + SL + TP lines ────────────────────────────────────────
    if sig.entries:
        ed = sig.entries[0]
        shapes.append(dict(type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end, y0=ed["entry"], y1=ed["entry"],
            line=dict(color=col, width=2.5, dash="dashdot")))
        annots.append(dict(x=chart_end, y=ed["entry"], xref="x", yref="y",
            text=f" OTE 0.618  {ed['entry']:{fmt}}", showarrow=False,
            font=dict(color=col, size=10, family="monospace"), xanchor="right",
            bgcolor="rgba(10,10,18,0.8)", bordercolor=col, borderwidth=1))

        shapes.append(dict(type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end, y0=ed["sl"], y1=ed["sl"],
            line=dict(color="#FF1744", width=1.5, dash="dash")))
        annots.append(dict(x=chart_end, y=ed["sl"], xref="x", yref="y",
            text=f" SL {cfg.sl_pips}p  {ed['sl']:{fmt}}", showarrow=False,
            font=dict(color="#FF1744", size=10, family="monospace"), xanchor="right",
            bgcolor="rgba(10,10,18,0.7)"))

        shapes.append(dict(type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=chart_end, y0=ed["tp"], y1=ed["tp"],
            line=dict(color="#00E676", width=1.5, dash="dot")))
        annots.append(dict(x=chart_end, y=ed["tp"], xref="x", yref="y",
            text=f" TP 1:2R  {ed['tp']:{fmt}}", showarrow=False,
            font=dict(color="#00E676", size=10, family="monospace"), xanchor="right",
            bgcolor="rgba(10,10,18,0.7)"))

    # ── 8. Trade result box + BLACK zone border ──────────────────────────────
    if trade and trade.get("entry_time") and trade.get("exit_time"):
        tc = "rgba(0,230,118,0.22)" if trade["result"] == "WIN" else "rgba(255,23,68,0.22)"
        bc = C["win"] if trade["result"] == "WIN" else C["loss"]

        shapes.append(dict(type="rect", xref="x", yref="y",
            x0=trade["entry_time"], x1=trade["exit_time"],
            y0=min(trade["entry"], trade["exit_price"]),
            y1=max(trade["entry"], trade["exit_price"]),
            fillcolor=tc, line=dict(color=bc, width=1.5)))

        # Black square box — full SL-to-TP zone while trade is active
        if sig.entries:
            ed_b = sig.entries[0]
            shapes.append(dict(type="rect", xref="x", yref="y",
                x0=trade["entry_time"], x1=trade["exit_time"],
                y0=min(ed_b["sl"], ed_b["tp"]),
                y1=max(ed_b["sl"], ed_b["tp"]),
                fillcolor="rgba(0,0,0,0)",
                line=dict(color="black", width=2.5),
                layer="above"))

        mid_y = (trade["entry"] + trade["exit_price"]) / 2
        annots.append(dict(x=trade["exit_time"], y=mid_y, xref="x", yref="y",
            text=f"{'✓ WIN' if trade['result']=='WIN' else '✗ LOSS'}  ${trade['pnl_usd']:+.0f}",
            showarrow=False, font=dict(color=bc, size=12, family="monospace"),
            xanchor="left", bgcolor="rgba(10,10,18,0.8)", bordercolor=bc, borderwidth=1))

    # ── Build figure ──────────────────────────────────────────────────────────
    result_str = ""
    if trade:
        rc = C["win"] if trade["result"] == "WIN" else C["loss"]
        result_str = (f" → <span style='color:{rc}'>"
                      f"{'WIN' if trade['result']=='WIN' else 'LOSS'}"
                      f" ${trade['pnl_usd']:+.0f}</span>")

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_zoom.index,
        open=df_zoom["open"], high=df_zoom["high"],
        low=df_zoom["low"],   close=df_zoom["close"],
        name="1m", whiskerwidth=0,
        increasing=dict(line=dict(color=C["buy"]),  fillcolor=C["buy"]),
        decreasing=dict(line=dict(color=C["sell"]), fillcolor=C["sell"]),
    ))
    fig.update_layout(
        shapes=shapes, annotations=annots,
        title=dict(
            text=(f"<b>{cfg.symbol}</b> #{sig_num}  "
                  f"<b style='color:{col}'>{dir_label}</b>  "
                  f"BOS @ {sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC"
                  f"{result_str}"),
            font=dict(size=14, color="white"),
        ),
        template="plotly_dark",
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        xaxis=dict(rangeslider=dict(visible=False), gridcolor=C["grid"], type="date"),
        yaxis=dict(gridcolor=C["grid"], tickformat=fmt, side="right"),
        height=560, margin=dict(l=10, r=180, t=60, b=30),
        showlegend=False,
    )
    return fig


# ── Summary / equity / filter charts ─────────────────────────────────────────

def _validity_badge(n: int, wr: float, target: int = 25) -> str:
    if n < target:
        pct = round(n / target * 100)
        return f"⏳ {n}/{target} trades — accumulating data ({pct}%)"
    if wr >= 70:
        return f"✅ VALIDATED  {n} trades  WR {wr:.1f}% ≥ 70%"
    return f"⚠️ LOW WR  {n} trades  WR {wr:.1f}% — review filters"


def summary_table(sym_results: dict) -> go.Figure:
    rows = []
    for symbol, data in sym_results.items():
        trades = data["trades"]
        n      = len(trades)
        wins   = sum(1 for t in trades if t["result"] == "WIN")
        net    = round(sum(t["pnl_usd"] for t in trades), 2)
        wr     = round(wins / n * 100, 1) if n else 0
        badge  = _validity_badge(n, wr)
        rows.append([symbol, data["stored_months"], data["setups"],
                     n, wins, n - wins, f"{wr}%", f"${net:+.2f}", badge])

    headers = ["Pair", "Data (mo)", "Setups", "Trades", "W", "L", "WR", "Net P&L", "Status"]
    fig = go.Figure(go.Table(
        header=dict(values=[f"<b>{h}</b>" for h in headers],
                    fill_color="#13131f", font=dict(color="white", size=12),
                    align="center", height=36),
        cells=dict(
            values=list(zip(*rows)) if rows else [[] for _ in headers],
            fill_color=[["#0d0d1a"] * len(rows)],
            font=dict(color=["white"] * len(rows), size=11),
            align="center", height=28),
    ))
    fig.update_layout(
        title="<b>Phase-404 Pro — Backtest Summary</b>",
        template="plotly_dark", paper_bgcolor=C["bg"],
        height=220 + len(rows) * 12, margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def equity_curve(all_trades: list, sym_results: dict) -> go.Figure:
    fig = go.Figure()
    for symbol in sym_results:
        sym_t = sorted(
            [t for t in all_trades if t["symbol"] == symbol and t["exit_time"]],
            key=lambda x: x["exit_time"])
        if not sym_t:
            continue
        bal, xs, ys = ACCOUNT_SIZE, [], []
        for t in sym_t:
            bal += t["pnl_usd"]
            xs.append(t["exit_time"]); ys.append(round(bal, 2))
        fig.add_trace(go.Scatter(x=xs, y=ys, name=symbol,
                                 mode="lines+markers",
                                 line=dict(width=2), marker=dict(size=5)))
    fig.add_hline(y=ACCOUNT_SIZE, line_dash="dot", line_color="#444",
                  annotation_text=f"Start ${ACCOUNT_SIZE:,.0f}")
    fig.update_layout(
        title="<b>Equity Curve</b>", yaxis_title="Balance ($)",
        template="plotly_dark", paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        height=340, margin=dict(l=60, r=40, t=50, b=40))
    return fig


def filter_breakdown(all_filter_logs: list) -> go.Figure:
    reasons: dict = {}
    for e in all_filter_logs:
        r = e["reason"].split("(")[0].split("<")[0].strip()
        reasons[r] = reasons.get(r, 0) + 1
    if not reasons:
        return go.Figure()
    items  = sorted(reasons.items(), key=lambda x: -x[1])
    labels = [x[0] for x in items]
    counts = [x[1] for x in items]
    fig = go.Figure(go.Bar(y=labels, x=counts, orientation="h",
                           marker_color="#6495ED", text=counts,
                           textposition="outside"))
    fig.update_layout(
        title="<b>Filtered-Out Setups — By Reason</b>",
        xaxis_title="Count", template="plotly_dark",
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg2"],
        height=max(280, len(labels) * 45 + 80),
        margin=dict(l=260, r=60, t=50, b=40))
    return fig


def trade_log_table(all_trades: list) -> go.Figure:
    if not all_trades:
        return go.Figure()
    rows, running = [], ACCOUNT_SIZE
    for i, t in enumerate(sorted(all_trades,
                                  key=lambda x: x["entry_time"] or datetime.min), 1):
        running += t["pnl_usd"]
        rows.append([
            i, t["symbol"], t["direction"],
            t["entry_time"].strftime("%m-%d %H:%M") if t["entry_time"] else "—",
            t["exit_time"].strftime("%m-%d %H:%M") if t["exit_time"] else "—",
            f"{t['sl_pips']:.0f}p",
            f"{t['entry']:.5g}", f"{t['sl']:.5g}",
            f"{t['tp']:.5g}", f"{t['exit_price']:.5g}",
            "✓ WIN" if t["result"] == "WIN" else "✗ LOSS",
            f"${t['pnl_usd']:+.2f}", f"${running:,.2f}",
        ])
    headers = ["#", "Pair", "Dir", "Entry", "Exit", "SL", "EntryPx", "SL Px",
               "TP Px", "ExitPx", "Result", "P&L", "Balance"]
    cell_vals  = list(zip(*rows))
    res_colors = [C["win"] if "WIN" in str(v) else C["loss"]
                  for v in cell_vals[headers.index("Result")]]
    pnl_colors = [C["win"] if float(str(v).replace("$","").replace("+","")) >= 0
                  else C["loss"] for v in cell_vals[headers.index("P&L")]]
    font_cols = []
    for i, h in enumerate(headers):
        if h == "Result": font_cols.append(res_colors)
        elif h == "P&L":  font_cols.append(pnl_colors)
        else:              font_cols.append(["#ddd"] * len(rows))

    fig = go.Figure(go.Table(
        header=dict(values=[f"<b>{h}</b>" for h in headers],
                    fill_color="#13131f", font=dict(color="white", size=11),
                    align="center", height=32),
        cells=dict(values=cell_vals,
                   fill_color=[["#0d0d1a", "#0e0e1a"] * (len(rows) // 2 + 1)][:len(rows)],
                   font=dict(color=font_cols, size=10),
                   align="center", height=26),
    ))
    fig.update_layout(
        title="<b>Full Trade Log</b>", template="plotly_dark",
        paper_bgcolor=C["bg"],
        height=min(180 + len(rows) * 27, 1400),
        margin=dict(l=10, r=10, t=50, b=10))
    return fig


# ── HTML Builder ──────────────────────────────────────────────────────────────

STYLE = """<style>
*{box-sizing:border-box}
body{background:#0a0a12;color:#ddd;font-family:'Segoe UI',sans-serif;margin:0;padding:24px 32px}
h1{color:#00D4AA;border-bottom:2px solid #00D4AA;padding-bottom:10px;margin-bottom:6px}
h2{color:#6495ED;margin-top:44px;font-size:19px}
h3{color:#FFD700;margin:4px 0 14px;font-size:13px;font-weight:normal}
.tagline{color:#888;font-size:14px;font-style:italic;margin-bottom:20px}
.cfg-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-bottom:32px}
.cfg-card{background:#0e0e1a;border:1px solid #1a1a3e;border-radius:10px;padding:14px 18px}
.cfg-card .pair{color:#FFD700;font-size:15px;font-weight:bold;margin-bottom:8px}
.cfg-card .row{display:flex;justify-content:space-between;font-size:12px;
               font-family:monospace;color:#aaa;margin:3px 0}
.cfg-card .row span{color:#ddd}
.stat-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:28px}
.stat-card{background:#0e0e1a;border:1px solid #1a1a3e;border-radius:10px;
           padding:12px 18px;min-width:130px;flex:1}
.stat-card .label{color:#666;font-size:11px;margin-bottom:3px}
.stat-card .value{font-size:21px;font-weight:bold;font-family:monospace}
.win{color:#00E676}.loss{color:#FF1744}.neutral{color:#FFD700}
.validity{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px}
.vbadge{padding:8px 14px;border-radius:8px;font-size:13px;
        font-family:monospace;border:1px solid #1a1a3e}
.vbadge.ok{border-color:#00E676;background:rgba(0,230,118,0.08)}
.vbadge.warn{border-color:#FFD700;background:rgba(255,215,0,0.08)}
.vbadge.acc{border-color:#6495ED;background:rgba(100,149,237,0.08)}
.section{margin-bottom:18px}
.filter-log{background:#0e0e1a;border:1px solid #1a1a3e;border-radius:8px;
            padding:14px 20px;font-family:monospace;font-size:12px;line-height:1.9;
            max-height:400px;overflow-y:auto}
.note{background:#131320;border-left:3px solid #6495ED;
      padding:10px 16px;margin:16px 0;border-radius:0 8px 8px 0;
      font-size:13px;color:#aaa}
</style>"""


def build_html(sym_results: dict, all_filter_logs: list) -> str:
    all_trades = [t for d in sym_results.values() for t in d["trades"]]
    total      = len(all_trades)
    wins       = sum(1 for t in all_trades if t["result"] == "WIN")
    net        = round(sum(t["pnl_usd"] for t in all_trades), 2)
    wr         = round(wins / total * 100, 1) if total else 0

    times  = [t["entry_time"] for t in all_trades if t["entry_time"]]
    d_from = min(times).strftime("%Y-%m-%d") if times else "N/A"
    d_to   = max(times).strftime("%Y-%m-%d") if times else "N/A"

    first_plotly = True
    def add_fig(fig):
        nonlocal first_plotly
        inc = "cdn" if first_plotly else False
        first_plotly = False
        return f'<div class="section">{fig.to_html(full_html=False, include_plotlyjs=inc)}</div>'

    parts = [f"""<!DOCTYPE html><html lang="en">
<head><meta charset="utf-8">
<title>Phase-404 Pro | Backtest Report</title>{STYLE}</head><body>
<h1>Phase-404 Professional Backtest</h1>
<p class="tagline">
  "Trade the retest after a liquidity sweep, in the direction of the trend."
  &nbsp;·&nbsp; 4 pairs, independently tuned &nbsp;·&nbsp; Target WR ≥ 70%
</p>
<div class="note">
  📦 <b>Data backend:</b> Redis (accumulates over runs) &nbsp;·&nbsp;
  Each run appends new <b>1m candles</b> (4 × 7-day chunks) — run weekly to build up to 2 years &nbsp;·&nbsp;
  <b>Statistical validity: 25 trades per pair required</b>
</div>"""]

    # Per-pair config cards
    parts.append('<div class="cfg-grid">')
    for symbol, data in sym_results.items():
        cfg = data["cfg"]
        bias_lbl = f"Last {cfg.session_bias_days} daily closes" if cfg.use_session_bias else "None"
        parts.append(f"""<div class="cfg-card">
  <div class="pair">{symbol}</div>
  <div class="row">SL <span>{cfg.sl_pips}p beyond sweep wick</span></div>
  <div class="row">Asian Range ≥ <span>{cfg.min_asian_range_pips}p</span></div>
  <div class="row">Sweep Wick ≥ <span>{cfg.min_wick_pips}p absolute</span></div>
  <div class="row">Fib Range ≥ <span>{cfg.min_fib_range_pips}p</span></div>
  <div class="row">Trade Window <span>{cfg.kill_start:02d}:00–{cfg.kill_end:02d}:00 UTC</span></div>
  <div class="row">Bias Filter <span>{bias_lbl}</span></div>
  <div class="row">Data Stored <span>{data['stored_months']:.1f} months</span></div>
</div>""")
    parts.append('</div>')

    # Stats row
    wr_class = "win" if wr >= 70 else ("neutral" if wr >= 50 else "loss")
    parts.append(f"""<div class="stat-row">
  <div class="stat-card"><div class="label">Date Range</div>
    <div class="value" style="font-size:13px">{d_from}<br>→ {d_to}</div></div>
  <div class="stat-card"><div class="label">Total Trades</div>
    <div class="value">{total}</div></div>
  <div class="stat-card"><div class="label">Win Rate</div>
    <div class="value {wr_class}">{wr}%</div></div>
  <div class="stat-card"><div class="label">Wins / Losses</div>
    <div class="value"><span class="win">{wins}W</span> / <span class="loss">{total-wins}L</span></div></div>
  <div class="stat-card"><div class="label">Net P&L</div>
    <div class="value {'win' if net>=0 else 'loss'}">${net:+.2f}</div></div>
  <div class="stat-card"><div class="label">Filtered Out</div>
    <div class="value" style="font-size:16px;color:#888">{len(all_filter_logs)}</div></div>
</div>""")

    # Validity badges
    parts.append('<h2>Statistical Validity</h2><div class="validity">')
    for symbol, data in sym_results.items():
        trades = data["trades"]
        n = len(trades)
        wins_s = sum(1 for t in trades if t["result"] == "WIN")
        wr_s = round(wins_s / n * 100, 1) if n else 0
        if n >= 25 and wr_s >= 70:
            cls, msg = "ok",   f"✅ {symbol}  {n} trades  WR {wr_s:.0f}%  VALIDATED"
        elif n >= 25:
            cls, msg = "warn", f"⚠️ {symbol}  {n} trades  WR {wr_s:.0f}%  Review filters"
        else:
            cls, msg = "acc",  f"⏳ {symbol}  {n}/25 trades — accumulating"
        parts.append(f'<div class="vbadge {cls}">{msg}</div>')
    parts.append('</div>')

    # Summary + equity
    parts.append("<h2>Performance Summary</h2>")
    parts.append(add_fig(summary_table(sym_results)))
    parts.append(add_fig(equity_curve(all_trades, sym_results)))
    parts.append(add_fig(filter_breakdown(all_filter_logs)))

    # Per-pair signal charts
    for symbol, data in sym_results.items():
        df      = data["df"]
        signals = data["signals"]
        trades  = data["trades"]
        cfg     = data["cfg"]
        n       = len(trades)
        wins_s  = sum(1 for t in trades if t["result"] == "WIN")
        wr_s    = round(wins_s / n * 100, 1) if n else 0
        net_s   = round(sum(t["pnl_usd"] for t in trades), 2)

        if not signals:
            parts.append(f"<h2>{symbol} — No setups passed filters</h2>")
            continue

        parts.append(f"""<h2>{symbol} — Signal Breakdown</h2>
<h3>{len(signals)} setups · {n} trades ·
<span class="{'win' if wr_s>=70 else ('neutral' if wr_s>=50 else 'loss')}">
WR {wr_s}%</span> · Net ${net_s:+.2f} · Data: {data['stored_months']:.1f} months</h3>""")

        for sig_num, sig in enumerate(signals, 1):
            matched = next(
                (t for t in trades if t["direction"] == sig.direction
                 and t.get("entry_time") and t["entry_time"] >= sig.timestamp),
                None)
            parts.append(add_fig(signal_zoom_chart(df, sig, matched, cfg, sig_num)))

    parts.append("<h2>Full Trade Log</h2>")
    parts.append(add_fig(trade_log_table(all_trades)))

    if all_filter_logs:
        parts.append('<h2>Filtered-Out Setups Log</h2>')
        parts.append('<div class="filter-log">')
        for e in all_filter_logs[:120]:
            parts.append(
                f"<span style='color:#888'>{e['ts'].strftime('%Y-%m-%d %H:%M')}</span>  "
                f"<span style='color:#6495ED'>{e.get('symbol','')}</span>  "
                f"→ {e['reason']}<br>")
        if len(all_filter_logs) > 120:
            parts.append(f"<br><i>... {len(all_filter_logs)-120} more entries not shown</i>")
        parts.append('</div>')

    parts.append("</body></html>")
    return "\n".join(parts)


# ── Runner ────────────────────────────────────────────────────────────────────

def run(do_update: bool = False):
    print("\n" + "=" * 70)
    print("  Phase-404 Professional Backtest — 4 Pairs, Redis Data Store")
    print("=" * 70)

    if do_update:
        print("\n[Data] Updating all pairs in Redis (1m — 4 × 7-day chunks + daily)...")
        for symbol, cfg in PAIR_CONFIGS.items():
            print(f"\n  [{symbol}]")
            update_1m(cfg.symbol, cfg.ticker, chunks=4, verbose=True)
            update_htf(cfg.symbol, cfg.ticker, interval="1d", verbose=True)
        print()

    sym_results:    dict = {}
    all_filter_logs: list = []

    for symbol, cfg in PAIR_CONFIGS.items():
        print(f"\n{'─'*70}")
        print(f"  [{symbol}]  {cfg.summary()}")
        print(f"{'─'*70}")

        # ── Load 1m data ────────────────────────────────────────────────────
        df = load(symbol, "1m")
        if df.empty:
            print("  No 1m data stored — downloading now (4 × 7-day chunks)...")
            df = update_1m(cfg.symbol, cfg.ticker, chunks=4, verbose=True)

        if df.empty:
            print("  Skipping — no data available"); continue

        s_ts, e_ts = df.index[0], df.index[-1]
        stored_months = round((e_ts - s_ts).days / 30.4, 1)
        print(f"  Data: {len(df):,} candles  "
              f"{s_ts.date()} → {e_ts.date()}  ({stored_months} months)")

        # ── Load daily data for session bias ────────────────────────────────
        daily_df = fetch_daily(cfg)
        if cfg.use_session_bias:
            print(f"  Session bias: {len(daily_df):,} daily candles" if not daily_df.empty
                  else "  Session bias: no daily data")
        else:
            print(f"  Session bias: disabled")

        # ── Generate signals ─────────────────────────────────────────────────
        print(f"  Generating signals...", end=" ", flush=True)
        signals, flog = generate_signals_pro(df, cfg, daily_df)
        for f in flog:
            f["symbol"] = symbol
        all_filter_logs.extend(flog)
        print(f"{len(signals)} setups  |  {len(flog)} filtered out")

        for sig in signals:
            print(f"    → {sig.direction:4s}  "
                  f"{sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC  "
                  f"Sweep@{sig.sweep_price:.5g}  BOS@{sig.bos_price:.5g}  "
                  f"OTE@{sig.entries[0]['entry']:.5g}")

        # ── Simulate trades ──────────────────────────────────────────────────
        trades = []
        if signals:
            print(f"  Simulating...", end=" ", flush=True)
            trades = simulate_pro(df, signals, cfg)
            wins  = sum(1 for t in trades if t["result"] == "WIN")
            n     = len(trades)
            wr    = round(wins / n * 100, 1) if n else 0
            net   = round(sum(t["pnl_usd"] for t in trades), 2)
            print(f"{n} trades  WR={wr}%  Net=${net:+.2f}")
            for t in trades:
                r = "✓" if t["result"] == "WIN" else "✗"
                print(f"    {r} {t['direction']:4s}  "
                      f"{t['entry_time'].strftime('%m-%d %H:%M') if t['entry_time'] else '?'}  "
                      f"P&L ${t['pnl_usd']:+.2f}")

        # ── Validity check ───────────────────────────────────────────────────
        n   = len(trades)
        wr  = round(sum(1 for t in trades if t["result"] == "WIN") / n * 100, 1) if n else 0
        print(f"  Validity: {_validity_badge(n, wr)}")

        sym_results[symbol] = {
            "df":            df,
            "cfg":           cfg,
            "signals":       signals,
            "trades":        trades,
            "stored_months": stored_months,
            "setups":        len(signals),
        }

    # ── Overall summary ──────────────────────────────────────────────────────
    all_t = [t for d in sym_results.values() for t in d["trades"]]
    total = len(all_t)
    wins  = sum(1 for t in all_t if t["result"] == "WIN")
    net   = round(sum(t["pnl_usd"] for t in all_t), 2)
    wr    = round(wins / total * 100, 1) if total else 0

    print(f"\n{'='*70}")
    print(f"  TOTAL TRADES  : {total}")
    print(f"  WIN RATE      : {wr}%  (target ≥ 70%)")
    print(f"  NET P&L       : ${net:+.2f}")
    print(f"{'='*70}")
    print()
    for symbol, data in sym_results.items():
        n  = len(data["trades"])
        print(f"  {symbol:<10} {n:>3} / 25 trades  "
              f"{'✅' if n >= 25 else '⏳'} "
              f"{'— run again in ~2 months to accumulate more data' if n < 25 else ''}")
    print()

    if not any(d["trades"] for d in sym_results.values()):
        print("No closed trades. Run with --update to fetch fresh data.")
        return

    print("[Report] Building HTML report...")
    html     = build_html(sym_results, all_filter_logs)
    out_file = OUT_DIR / "phase404_pro_report.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"[Report] Saved → {out_file}")

    import webbrowser
    webbrowser.open(str(out_file))


if __name__ == "__main__":
    do_update = "--update" in sys.argv
    run(do_update=do_update)
