"""
Phase-404 Signal Sketch — Zoomed-In Setup Visualizer
======================================================
Renders one chart per detected signal on EURUSD + GBPJPY.
Each chart shows a tight zoom window: Asian box → Sweep → BOS → OTE levels → trade result.

Run: python -m backtest.phase404_sketch
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

from backtest.phase404_signals import (
    generate_signals, get_asian_ranges, OTE_LEVELS, OTE_RR,
)
from backtest.phase404_backtest import simulate_all_levels, fetch, SYMBOLS, ACCOUNT_SIZE

OUT_DIR = Path(__file__).parent.parent / "data" / "phase404"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SKETCH_SYMBOLS = ["EURUSD", "GBPJPY"]

# ── Palette ───────────────────────────────────────────────────────────────────
C = {
    "bg":         "#0a0a12",
    "bg2":        "#0e0e1a",
    "grid":       "#1a1a2e",
    "asian_fill": "rgba(100,149,237,0.13)",
    "asian_line": "#6495ED",
    "sweep_up":   "#FF6B35",
    "sweep_dn":   "#FF6B35",
    "bos":        "#FFD700",
    "ote50":      "#A0C4FF",
    "ote618":     "#00D4AA",
    "ote75":      "#C77DFF",
    "sl":         "#FF1744",
    "tp":         "#00E676",
    "win":        "rgba(0,230,118,0.20)",
    "loss":       "rgba(255,23,68,0.20)",
    "win_border": "#00E676",
    "loss_border":"#FF1744",
    "bull_candle": "#00CC66",
    "bear_candle": "#FF4444",
}

OTE_COLORS = {0.50: C["ote50"], 0.618: C["ote618"], 0.75: C["ote75"]}


# ── Zoom window around a signal ───────────────────────────────────────────────

def zoom_window(df: pd.DataFrame, sig, pre_bars: int = 60, post_bars: int = 100) -> pd.DataFrame:
    """Return a slice of df centered around the signal's BOS timestamp."""
    try:
        idx = df.index.get_loc(sig.timestamp)
    except KeyError:
        idx = df.index.searchsorted(sig.timestamp)
    if isinstance(idx, slice):
        idx = idx.start

    # Include candles from Asian session start (so box is visible)
    start = max(0, idx - pre_bars)
    end   = min(len(df), idx + post_bars)
    return df.iloc[start:end].copy()


# ── Single-signal sketch chart ────────────────────────────────────────────────

def sketch_signal(df_zoom: pd.DataFrame, sig, trades: list[dict],
                  symbol: str, sig_num: int) -> go.Figure:
    """
    Draw one zoomed chart per signal.
    Layers:
      1. Candlesticks
      2. Asian range shaded box + H/L/Mid lines
      3. Sweep candle highlight (orange border)
      4. BOS horizontal line (gold)
      5. OTE 0.5 / 0.618 / 0.75 entry lines + SL + TP per level
      6. Fibonacci retracement zone (shaded between OTE 0.5 and 0.75)
      7. Trade result rectangles (green/red fill)
      8. Annotations: directional label, all price levels
    """
    direction  = sig.direction
    arrow      = "▼ SELL" if direction == "SELL" else "▲ BUY"
    title_col  = C["bear_candle"] if direction == "SELL" else C["bull_candle"]

    shapes, annotations = [], []

    # ── Asian session box ────────────────────────────────────────────────────
    date_str = str(sig.timestamp.date())
    ar_x0    = pd.Timestamp(f"{date_str} 01:00", tz="UTC")
    ar_x1    = pd.Timestamp(f"{date_str} 05:00", tz="UTC")

    shapes.append(dict(
        type="rect", xref="x", yref="y",
        x0=ar_x0, x1=ar_x1,
        y0=sig.asian_low, y1=sig.asian_high,
        fillcolor=C["asian_fill"],
        line=dict(color=C["asian_line"], width=1.5),
        opacity=1,
    ))

    # Asian H / L / Mid labels inside box
    box_mid_x = ar_x0 + (ar_x1 - ar_x0) / 2
    for price, label in [
        (sig.asian_high, f"AsH {sig.asian_high:.5f}"),
        (sig.asian_low,  f"AsL {sig.asian_low:.5f}"),
    ]:
        annotations.append(dict(
            x=ar_x0, y=price, xref="x", yref="y",
            text=f"<b>{label}</b>",
            showarrow=False,
            font=dict(color=C["asian_line"], size=10, family="monospace"),
            xanchor="left",
            bgcolor="rgba(10,10,18,0.6)",
        ))

    # Asian H/L extended lines (dashed)
    for price in [sig.asian_high, sig.asian_low]:
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=ar_x1, x1=df_zoom.index[-1],
            y0=price, y1=price,
            line=dict(color=C["asian_line"], width=1, dash="dash"),
            opacity=0.5,
        ))

    # ── Sweep candle border highlight ────────────────────────────────────────
    # Find the sweep candle: last candle before BOS that wicked past Asian H/L
    try:
        bos_idx = df_zoom.index.get_loc(sig.timestamp)
    except KeyError:
        bos_idx = len(df_zoom) - 1

    # Search backward for sweep candle (within 30 bars before BOS)
    sweep_bar_idx = None
    for k in range(max(0, bos_idx - 30), bos_idx):
        bar = df_zoom.iloc[k]
        if direction == "SELL" and bar["high"] >= sig.asian_high:
            sweep_bar_idx = k
        elif direction == "BUY" and bar["low"] <= sig.asian_low:
            sweep_bar_idx = k

    if sweep_bar_idx is not None:
        sw_ts = df_zoom.index[sweep_bar_idx]
        sw_bar = df_zoom.iloc[sweep_bar_idx]
        # Orange box around the sweep candle
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=sw_ts - pd.Timedelta(minutes=2),
            x1=sw_ts + pd.Timedelta(minutes=2),
            y0=sw_bar["low"] * 0.9999,
            y1=sw_bar["high"] * 1.0001,
            fillcolor="rgba(255,107,53,0.0)",
            line=dict(color=C["sweep_up"], width=2.5),
        ))
        # Sweep label with arrow
        sweep_label_y = sw_bar["high"] if direction == "SELL" else sw_bar["low"]
        annotations.append(dict(
            x=sw_ts, y=sweep_label_y,
            xref="x", yref="y",
            text=f"<b>SWEEP</b>",
            showarrow=True, arrowhead=2,
            arrowcolor=C["sweep_up"],
            arrowsize=1.4, arrowwidth=2,
            font=dict(color=C["sweep_up"], size=12, family="monospace"),
            ay=-40 if direction == "SELL" else 40,
            ax=0,
            bgcolor="rgba(10,10,18,0.7)",
        ))

    # ── BOS level ────────────────────────────────────────────────────────────
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=df_zoom.index[0], x1=df_zoom.index[-1],
        y0=sig.bos_price, y1=sig.bos_price,
        line=dict(color=C["bos"], width=1.8, dash="dot"),
        opacity=0.9,
    ))
    annotations.append(dict(
        x=sig.timestamp, y=sig.bos_price,
        xref="x", yref="y",
        text=f"<b>BOS ✔ {sig.bos_price:.5f}</b>",
        showarrow=True, arrowhead=1,
        arrowcolor=C["bos"], arrowwidth=1.5,
        font=dict(color=C["bos"], size=11, family="monospace"),
        ay=35 if direction == "SELL" else -35,
        bgcolor="rgba(10,10,18,0.7)",
    ))

    # ── Fibonacci OTE zone (shaded between 0.5 and 0.75) ────────────────────
    entry_50  = next((e for e in sig.entries if abs(e["level"] - 0.50)  < 0.01), None)
    entry_618 = next((e for e in sig.entries if abs(e["level"] - 0.618) < 0.01), None)
    entry_75  = next((e for e in sig.entries if abs(e["level"] - 0.75)  < 0.01), None)

    if entry_50 and entry_75:
        y0 = min(entry_50["entry"], entry_75["entry"])
        y1 = max(entry_50["entry"], entry_75["entry"])
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=sig.timestamp, x1=df_zoom.index[-1],
            y0=y0, y1=y1,
            fillcolor="rgba(0,212,170,0.08)",
            line=dict(color="rgba(0,212,170,0.2)", width=0),
        ))

    # ── OTE entry levels + SL + TP per level ────────────────────────────────
    for entry_data in sig.entries:
        lvl   = entry_data["level"]
        col   = OTE_COLORS.get(lvl, "#ffffff")
        e_px  = entry_data["entry"]
        sl_px = entry_data["sl"]
        tp_px = entry_data["tp"]
        rr    = entry_data["rr"]

        # Entry line
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=df_zoom.index[-1],
            y0=e_px, y1=e_px,
            line=dict(color=col, width=2, dash="dashdot"),
        ))
        annotations.append(dict(
            x=df_zoom.index[-1], y=e_px,
            xref="x", yref="y",
            text=f" OTE {lvl} → 1:{rr}R  {e_px:.5f}",
            showarrow=False,
            font=dict(color=col, size=10, family="monospace"),
            xanchor="right",
            bgcolor="rgba(10,10,18,0.7)",
        ))

    # SL and TP use outermost level (0.75 entry, which has widest SL)
    ref_entry = entry_75 or entry_618 or entry_50
    if ref_entry:
        # SL line
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sig.timestamp, x1=df_zoom.index[-1],
            y0=ref_entry["sl"], y1=ref_entry["sl"],
            line=dict(color=C["sl"], width=1.5, dash="dash"),
        ))
        annotations.append(dict(
            x=df_zoom.index[-1], y=ref_entry["sl"],
            xref="x", yref="y",
            text=f" SL {ref_entry['sl']:.5f}",
            showarrow=False,
            font=dict(color=C["sl"], size=10, family="monospace"),
            xanchor="right",
            bgcolor="rgba(10,10,18,0.7)",
        ))

        # TP markers (per level — stacked)
        for entry_data in sig.entries:
            col = OTE_COLORS.get(entry_data["level"], "#ffffff")
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=sig.timestamp, x1=df_zoom.index[-1],
                y0=entry_data["tp"], y1=entry_data["tp"],
                line=dict(color=col, width=1, dash="dot"),
                opacity=0.5,
            ))
            annotations.append(dict(
                x=df_zoom.index[-1], y=entry_data["tp"],
                xref="x", yref="y",
                text=f" TP{entry_data['rr']}R  {entry_data['tp']:.5f}",
                showarrow=False,
                font=dict(color=col, size=9, family="monospace"),
                xanchor="right",
                bgcolor="rgba(10,10,18,0.5)",
            ))

    # ── Trade result rectangles ───────────────────────────────────────────────
    sig_trades = [
        t for t in trades
        if t["entry_time"] and t["entry_time"] >= sig.timestamp
        and t["direction"] == direction
        and t.get("entry_time") in df_zoom.index or True
    ]
    drawn = set()
    for t in sig_trades[:9]:  # all 3 levels × up to 3 per level
        key = (round(t["entry"], 5), t["result"])
        if key in drawn:
            continue
        drawn.add(key)

        if not (t["entry_time"] and t["exit_time"]):
            continue

        t_col    = C["win"] if t["result"] == "WIN" else C["loss"]
        t_border = C["win_border"] if t["result"] == "WIN" else C["loss_border"]

        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=t["entry_time"], x1=t["exit_time"],
            y0=min(t["entry"], t["exit_price"]),
            y1=max(t["entry"], t["exit_price"]),
            fillcolor=t_col,
            line=dict(color=t_border, width=1),
        ))

        # Result label
        pnl_sign = "+" if t["pnl_usd"] >= 0 else ""
        annotations.append(dict(
            x=t["exit_time"],
            y=(t["entry"] + t["exit_price"]) / 2,
            xref="x", yref="y",
            text=f"{'✓' if t['result']=='WIN' else '✗'} {pnl_sign}{t['pnl_usd']:.0f}$",
            showarrow=False,
            font=dict(color=t_border, size=10, family="monospace", weight="bold"),
            xanchor="left",
            bgcolor="rgba(10,10,18,0.7)",
        ))

    # ── Build figure ─────────────────────────────────────────────────────────
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_zoom.index,
        open=df_zoom["open"], high=df_zoom["high"],
        low=df_zoom["low"],  close=df_zoom["close"],
        name="Price",
        increasing=dict(line=dict(color=C["bull_candle"], width=1),
                        fillcolor=C["bull_candle"]),
        decreasing=dict(line=dict(color=C["bear_candle"], width=1),
                        fillcolor=C["bear_candle"]),
        whiskerwidth=0,
    ))

    fig.update_layout(
        shapes=shapes,
        annotations=annotations,
        title=dict(
            text=(
                f"<b style='color:{title_col}'>{arrow}</b>  ·  "
                f"<b>{symbol}</b>  Signal #{sig_num}  ·  "
                f"BOS @ {sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC"
            ),
            font=dict(size=15, color="white"),
        ),
        template="plotly_dark",
        paper_bgcolor=C["bg"],
        plot_bgcolor=C["bg2"],
        xaxis=dict(
            rangeslider=dict(visible=False),
            gridcolor=C["grid"], showgrid=True,
            type="date",
        ),
        yaxis=dict(
            gridcolor=C["grid"], showgrid=True,
            tickformat=".5f",
            side="right",
        ),
        height=560,
        margin=dict(l=20, r=160, t=60, b=40),
        showlegend=False,
    )

    # Add a legend box manually via annotation
    asian_c   = C["asian_line"]
    sweep_c   = C["sweep_up"]
    bos_c     = C["bos"]
    ote50_c   = C["ote50"]
    ote618_c  = C["ote618"]
    ote75_c   = C["ote75"]
    sl_c      = C["sl"]
    win_c     = C["win_border"]
    loss_c    = C["loss_border"]
    legend_lines = [
        f"<span style='color:{asian_c}'>■</span> Asian Range",
        f"<span style='color:{sweep_c}'>■</span> Sweep Candle",
        f"<span style='color:{bos_c}'>■</span> BOS Level",
        f"<span style='color:{ote50_c}'>─</span> OTE 0.50 → 1:2R",
        f"<span style='color:{ote618_c}'>─</span> OTE 0.618 → 1:3R",
        f"<span style='color:{ote75_c}'>─</span> OTE 0.75 → 1:4R",
        f"<span style='color:{sl_c}'>─</span> Stop Loss",
        f"<span style='color:{win_c}'>■</span> WIN trade",
        f"<span style='color:{loss_c}'>■</span> LOSS trade",
    ]
    fig.add_annotation(
        x=1.01, y=0.98,
        xref="paper", yref="paper",
        text="<br>".join(legend_lines),
        showarrow=False,
        align="left",
        font=dict(size=10, family="monospace"),
        bgcolor="rgba(14,14,26,0.9)",
        bordercolor="#333",
        borderwidth=1,
        xanchor="left",
        yanchor="top",
    )

    return fig


# ── HTML builder ──────────────────────────────────────────────────────────────

STYLE = """
<style>
* { box-sizing: border-box; }
body {
    background: #0a0a12; color: #ddd;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    margin: 0; padding: 24px 32px;
}
h1 { color: #00D4AA; border-bottom: 2px solid #00D4AA; padding-bottom: 10px; font-size: 28px; }
h2 { color: #6495ED; margin-top: 48px; font-size: 20px; letter-spacing: 1px; }
h3 { color: #FFD700; margin: 6px 0 16px; font-size: 15px; font-weight: normal; }

.strategy-box {
    background: #0e0e1a; border: 1px solid #6495ED;
    border-radius: 12px; padding: 20px 28px;
    margin-bottom: 32px; font-size: 14px; line-height: 2;
}
.tag { background: #1a1a3e; border-radius: 4px; padding: 2px 10px;
       color: #FFD700; margin: 0 4px; font-family: monospace; }

.signal-block {
    background: #0e0e1a; border-radius: 12px;
    padding: 16px; margin-bottom: 36px;
    border-left: 3px solid #6495ED;
}
.signal-block.sell { border-left-color: #FF4444; }
.signal-block.buy  { border-left-color: #00CC66; }

.meta-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 8px; margin-top: 12px;
}
.meta-item {
    background: #13131f; border-radius: 8px; padding: 10px 14px;
    font-family: monospace; font-size: 13px;
}
.meta-item .label { color: #888; font-size: 11px; display: block; margin-bottom: 2px; }
.meta-item .value { color: #eee; font-size: 14px; }
.win  { color: #00E676 !important; }
.loss { color: #FF1744 !important; }

.summary-table { width: 100%; border-collapse: collapse; margin-top: 16px; }
.summary-table th {
    background: #13131f; color: #aaa; padding: 10px 14px;
    text-align: left; font-size: 13px; border-bottom: 1px solid #222;
}
.summary-table td {
    padding: 9px 14px; border-bottom: 1px solid #1a1a28;
    font-family: monospace; font-size: 13px;
}
.summary-table tr:last-child { font-weight: bold; color: #FFD700; background: #131320; }
</style>
"""


def build_html(sym_results: dict) -> str:
    parts = [f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>Phase-404 Signal Sketches — EURUSD &amp; GBPJPY</title>
{STYLE}
</head><body>
<h1>Phase-404 — Signal Sketches</h1>
<div class="strategy-box">
  <b style="color:#00D4AA; font-size:16px;">Strategy Rules</b><br>
  <b>Step 1:</b> Mark Asian session H/L &nbsp;<span class="tag">20:00–00:00 EST = 01:00–05:00 UTC</span><br>
  <b>Step 2:</b> Wait for liquidity sweep of Asian high <i>or</i> low<br>
  <b>Step 3:</b> Confirm Break of Structure (BOS) after sweep<br>
  <b>Step 4:</b> OTE Fibonacci limits &nbsp;
  <span class="tag">0.50 → 1:2R</span>
  <span class="tag">0.618 → 1:3R</span>
  <span class="tag">0.75 → 1:4R</span>
</div>
"""]

    first_plotlyjs = True
    total_trades, total_wins, total_pnl = 0, 0, 0.0

    for symbol, data in sym_results.items():
        signals  = data["signals"]
        trades   = data["trades"]
        df       = data["df"]

        wins_sym = sum(1 for t in trades if t["result"] == "WIN")
        tot_sym  = len(trades)
        net_sym  = sum(t["pnl_usd"] for t in trades)

        total_trades += tot_sym
        total_wins   += wins_sym
        total_pnl    += net_sym

        wr = round(wins_sym / tot_sym * 100, 1) if tot_sym else 0
        wr_class = "win" if wr >= 50 else "loss"

        parts.append(f"""
<h2>{symbol}</h2>
<h3>{len(signals)} setups detected &nbsp;·&nbsp; {tot_sym} trades simulated &nbsp;·&nbsp;
<span class="{wr_class}">Win Rate {wr}%</span> &nbsp;·&nbsp;
<span class="{'win' if net_sym >= 0 else 'loss'}">Net P&L ${net_sym:+.2f}</span>
</h3>
""")

        for sig_num, sig in enumerate(signals, 1):
            df_zoom = zoom_window(df, sig, pre_bars=70, post_bars=250)
            sig_trades = simulate_all_levels(df_zoom, [sig], symbol)

            # Use parent trades if zoom simulation misses (entry outside window)
            if not sig_trades:
                sig_trades = [
                    t for t in trades
                    if t["direction"] == sig.direction
                    and t.get("entry_time") and t["entry_time"] >= sig.timestamp
                ]

            direction  = sig.direction
            dir_class  = "sell" if direction == "SELL" else "buy"
            dir_label  = "▼ SELL" if direction == "SELL" else "▲ BUY"
            dir_color  = "#FF4444" if direction == "SELL" else "#00CC66"

            # Aggregate results for this signal
            sig_wins = sum(1 for t in sig_trades if t["result"] == "WIN")
            sig_tot  = len(sig_trades)
            sig_net  = sum(t["pnl_usd"] for t in sig_trades)

            parts.append(f"""
<div class="signal-block {dir_class}">
  <b style="color:{dir_color}; font-size:16px;">{dir_label} — Setup #{sig_num}</b>
  &nbsp;&nbsp;<span style="color:#888; font-size:13px;">BOS @ {sig.timestamp.strftime('%Y-%m-%d %H:%M')} UTC</span>
  <div class="meta-grid">
    <div class="meta-item"><span class="label">Asian High</span><span class="value">{sig.asian_high:.5f}</span></div>
    <div class="meta-item"><span class="label">Asian Low</span><span class="value">{sig.asian_low:.5f}</span></div>
    <div class="meta-item"><span class="label">Sweep Extreme</span><span class="value">{sig.sweep_price:.5f}</span></div>
    <div class="meta-item"><span class="label">BOS Level</span><span class="value">{sig.bos_price:.5f}</span></div>
    <div class="meta-item"><span class="label">OTE 0.50 Entry</span><span class="value">{next((e['entry'] for e in sig.entries if abs(e['level']-0.50)<0.01), 'N/A')}</span></div>
    <div class="meta-item"><span class="label">OTE 0.618 Entry</span><span class="value">{next((e['entry'] for e in sig.entries if abs(e['level']-0.618)<0.01), 'N/A')}</span></div>
    <div class="meta-item"><span class="label">OTE 0.75 Entry</span><span class="value">{next((e['entry'] for e in sig.entries if abs(e['level']-0.75)<0.01), 'N/A')}</span></div>
    <div class="meta-item"><span class="label">Trades Hit</span><span class="value">{sig_tot} trades</span></div>
    <div class="meta-item"><span class="label">Wins / Losses</span><span class="value"><span class="win">{sig_wins}W</span> / <span class="loss">{sig_tot-sig_wins}L</span></span></div>
    <div class="meta-item"><span class="label">Net P&L</span><span class="value {'win' if sig_net >= 0 else 'loss'}">${sig_net:+.2f}</span></div>
  </div>
</div>
""")

            fig = sketch_signal(df_zoom, sig, sig_trades, symbol, sig_num)
            plotly_args = {"full_html": False, "include_plotlyjs": "cdn" if first_plotlyjs else False}
            parts.append(f'<div style="margin-bottom:8px;">{fig.to_html(**plotly_args)}</div>')
            first_plotlyjs = False

    # ── Global summary table ──────────────────────────────────────────────────
    total_wr  = round(total_wins / total_trades * 100, 1) if total_trades else 0
    wr_cls    = "win" if total_wr >= 50 else "loss"

    parts.append(f"""
<h2>Overall Summary — EURUSD + GBPJPY</h2>
<table class="summary-table">
  <thead><tr>
    <th>Pair</th><th>Setups</th><th>Trades</th><th>Wins</th>
    <th>Losses</th><th>Win Rate</th><th>Net P&L</th>
  </tr></thead>
  <tbody>
""")

    for symbol, data in sym_results.items():
        trades = data["trades"]
        sigs   = data["signals"]
        wins   = sum(1 for t in trades if t["result"] == "WIN")
        tot    = len(trades)
        net    = sum(t["pnl_usd"] for t in trades)
        wr_s   = round(wins / tot * 100, 1) if tot else 0
        parts.append(f"""<tr>
  <td>{symbol}</td><td>{len(sigs)}</td><td>{tot}</td>
  <td class="win">{wins}</td><td class="loss">{tot-wins}</td>
  <td class="{'win' if wr_s>=50 else 'loss'}">{wr_s}%</td>
  <td class="{'win' if net>=0 else 'loss'}">${net:+.2f}</td>
</tr>
""")

    parts.append(f"""<tr>
  <td>TOTAL</td><td>—</td><td>{total_trades}</td>
  <td>{total_wins}</td><td>{total_trades-total_wins}</td>
  <td class="{wr_cls}">{total_wr}%</td>
  <td class="{'win' if total_pnl>=0 else 'loss'}">${total_pnl:+.2f}</td>
</tr>
  </tbody>
</table>
<br><br>
""")

    parts.append("</body></html>")
    return "\n".join(parts)


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 60)
    print("  Phase-404 Signal Sketch — EURUSD + GBPJPY")
    print("=" * 60)

    sym_results = {}

    for symbol in SKETCH_SYMBOLS:
        print(f"\n[{symbol}] Fetching data...", end=" ", flush=True)
        df = fetch(symbol)
        if df.empty:
            print("NO DATA — skipped")
            continue
        print(f"{len(df)} candles")

        print(f"[{symbol}] Detecting signals...", end=" ", flush=True)
        signals = generate_signals(df, symbol)
        print(f"{len(signals)} setups")

        if not signals:
            print(f"[{symbol}] No signals found.")
            continue

        print(f"[{symbol}] Simulating trades...", end=" ", flush=True)
        trades = simulate_all_levels(df, signals, symbol)
        wins   = sum(1 for t in trades if t["result"] == "WIN")
        print(f"{len(trades)} trades | WR={round(wins/len(trades)*100,1) if trades else 0}%")

        sym_results[symbol] = {"signals": signals, "trades": trades, "df": df}

    if not sym_results:
        print("\nNo signals detected for EURUSD or GBPJPY. Try after Monday market open.")
        return

    print("\n[Sketch] Building zoomed-in signal charts...")
    html = build_html(sym_results)

    out_file = OUT_DIR / "phase404_sketches.html"
    out_file.write_text(html, encoding="utf-8")

    print(f"\n[Sketch] Saved → {out_file}")
    print("=" * 60)

    import webbrowser
    webbrowser.open(str(out_file))


if __name__ == "__main__":
    run()
