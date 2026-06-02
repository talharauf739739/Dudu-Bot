"""
Phase-404 Backtest + Visualization
====================================
Runs the Phase-404 strategy across EURUSD, GBPUSD, XAUUSD, NAS100.
Generates a full HTML report with:
  - Candlestick chart with Asian range, sweep, BOS, OTE levels, trades
  - Equity curve per instrument
  - Win rate per OTE level (0.5 / 0.618 / 0.75)
  - P&L distribution histogram
  - Summary stats table

Run: python -m backtest.phase404_backtest
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
import plotly.subplots as sp
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from pathlib import Path

from backtest.phase404_signals import (
    generate_signals, get_asian_ranges,
    signals_to_df, OTE_LEVELS, OTE_RR,
)
from backtest.engine import BacktestEngine

# ── Config ─────────────────────────────────────────────────────────────────────
SYMBOLS = {
    "EURUSD":  {"ticker": "EURUSD=X", "interval": "5m",  "days": 7,  "pip": 0.0001, "pip_val": 10.0},
    "GBPUSD":  {"ticker": "GBPUSD=X", "interval": "5m",  "days": 7,  "pip": 0.0001, "pip_val": 10.0},
    "AUDUSD":  {"ticker": "AUDUSD=X", "interval": "5m",  "days": 7,  "pip": 0.0001, "pip_val": 10.0},
    "USDJPY":  {"ticker": "USDJPY=X", "interval": "5m",  "days": 7,  "pip": 0.01,   "pip_val": 10.0},
    "GBPJPY":  {"ticker": "GBPJPY=X", "interval": "5m",  "days": 7,  "pip": 0.01,   "pip_val": 10.0},
    "NAS100":  {"ticker": "^NDX",     "interval": "15m", "days": 60, "pip": 1.0,    "pip_val": 1.0},
    "US30":    {"ticker": "^DJI",     "interval": "15m", "days": 60, "pip": 1.0,    "pip_val": 1.0},
}

ACCOUNT_SIZE = 10_000.0
RISK_PCT     = 1.0
PROP_RULES   = {"daily_dd_pct": 5.0, "max_dd_pct": 10.0}
OUT_DIR      = Path(__file__).parent.parent / "data" / "phase404"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {
    "asian_box":  "rgba(100,149,237,0.12)",
    "asian_line": "#6495ED",
    "sweep":      "#FF6B35",
    "bos":        "#FFD700",
    "sell_entry": "#FF4444",
    "buy_entry":  "#00CC66",
    "sl":         "#FF0000",
    "tp":         "#00FF88",
    "win_bar":    "#00C853",
    "loss_bar":   "#FF1744",
    "equity":     "#00D4AA",
}

# ── Data Fetcher ───────────────────────────────────────────────────────────────

def fetch(symbol: str) -> pd.DataFrame:
    cfg  = SYMBOLS[symbol]
    end  = datetime.utcnow()
    start = end - timedelta(days=cfg["days"])
    df = yf.download(
        cfg["ticker"], start=start, end=end,
        interval=cfg["interval"], progress=False, auto_adjust=True,
    )
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


# ── Trade Simulation (per OTE level) ──────────────────────────────────────────

def simulate_all_levels(df: pd.DataFrame, signals, symbol: str) -> list[dict]:
    """
    Simulate all 3 OTE entry levels independently.
    For each signal, forward-scan the OHLC to see which entry is hit and result.
    """
    trades = []
    for sig in signals:
        # Find the index of the BOS candle in df
        try:
            bos_loc = df.index.get_loc(sig.timestamp)
        except KeyError:
            # Find nearest
            bos_loc = df.index.searchsorted(sig.timestamp)
        if isinstance(bos_loc, slice):
            bos_loc = bos_loc.start

        for entry_data in sig.entries:
            entry  = entry_data["entry"]
            sl     = entry_data["sl"]
            tp     = entry_data["tp"]
            rr     = entry_data["rr"]
            level  = entry_data["level"]

            result      = "OPEN"
            exit_price  = 0.0
            hold_bars   = 0
            entry_time  = None
            exit_time   = None

            # Forward scan: first check if entry level is reached, then monitor
            entry_hit = False
            for j in range(bos_loc + 1, min(bos_loc + 500, len(df))):
                bar = df.iloc[j]

                # Check entry hit
                if not entry_hit:
                    if sig.direction == "SELL" and bar["high"] >= entry:
                        entry_hit = True
                        entry_time = df.index[j]
                    elif sig.direction == "BUY" and bar["low"] <= entry:
                        entry_hit = True
                        entry_time = df.index[j]

                if not entry_hit:
                    continue

                hold_bars += 1

                # Check SL / TP
                if sig.direction == "SELL":
                    if bar["high"] >= sl:
                        result = "LOSS"; exit_price = sl; exit_time = df.index[j]; break
                    if bar["low"] <= tp:
                        result = "WIN";  exit_price = tp; exit_time = df.index[j]; break
                else:
                    if bar["low"] <= sl:
                        result = "LOSS"; exit_price = sl; exit_time = df.index[j]; break
                    if bar["high"] >= tp:
                        result = "WIN";  exit_price = tp; exit_time = df.index[j]; break

            if result == "OPEN":
                continue   # skip untriggered or still open

            # P&L
            cfg = SYMBOLS[symbol]
            sl_pips = abs(entry - sl) / cfg["pip"]
            risk_usd = ACCOUNT_SIZE * (RISK_PCT / 100)
            lot = round(risk_usd / (sl_pips * cfg["pip_val"]), 2)
            lot = max(0.01, min(lot, 10.0))

            if sig.direction == "SELL":
                pnl = round((entry - exit_price) / cfg["pip"] * cfg["pip_val"] * lot, 2)
            else:
                pnl = round((exit_price - entry) / cfg["pip"] * cfg["pip_val"] * lot, 2)

            trades.append({
                "symbol":      symbol,
                "direction":   sig.direction,
                "ote_level":   level,
                "rr_target":   rr,
                "entry":       entry,
                "sl":          sl,
                "tp":          tp,
                "exit_price":  exit_price,
                "result":      result,
                "pnl_usd":     pnl,
                "hold_bars":   hold_bars,
                "entry_time":  entry_time,
                "exit_time":   exit_time,
                "asian_high":  sig.asian_high,
                "asian_low":   sig.asian_low,
                "sweep_price": sig.sweep_price,
                "bos_price":   sig.bos_price,
            })

    return trades


# ── Chart: Candlestick with annotations ───────────────────────────────────────

def draw_signal_chart(df: pd.DataFrame, signals, trades: list[dict], symbol: str) -> go.Figure:
    """Show last 5 signals on a candlestick chart with all annotations."""

    # Limit to last 300 candles for readability
    plot_df  = df.tail(300).copy()
    sig_tail = [s for s in signals if s.timestamp >= plot_df.index[0]][-5:]

    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=plot_df.index, open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"],
        name=symbol, increasing_line_color="#00CC66", decreasing_line_color="#FF4444",
    ))

    shapes, annotations = [], []
    asian_ranges = get_asian_ranges(plot_df)

    # Asian range shaded boxes
    for date_str, ar in list(asian_ranges.items())[-7:]:
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=pd.Timestamp(f"{date_str} 01:00", tz="UTC"),
            x1=pd.Timestamp(f"{date_str} 05:00", tz="UTC"),
            y0=ar.low, y1=ar.high,
            fillcolor=COLORS["asian_box"], line_color=COLORS["asian_line"],
            line_width=1, opacity=0.8,
        ))
        # Asian H/L lines
        x0 = pd.Timestamp(f"{date_str} 05:00", tz="UTC")
        x1 = plot_df.index[-1]
        for price, label in [(ar.high, "AsH"), (ar.low, "AsL"), (ar.mid, "AsMid")]:
            dash = "dot" if "Mid" in label else "dash"
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=x0, x1=x1, y0=price, y1=price,
                line=dict(color=COLORS["asian_line"], width=1, dash=dash),
            ))
            annotations.append(dict(
                x=x1, y=price, xref="x", yref="y",
                text=f"<b>{label}</b>", showarrow=False,
                font=dict(color=COLORS["asian_line"], size=10),
                xanchor="right",
            ))

    # Signals: sweep + BOS + OTE levels + trades
    for sig in sig_tail:
        col = COLORS["sell_entry"] if sig.direction == "SELL" else COLORS["buy_entry"]
        sym_arrow = "▼" if sig.direction == "SELL" else "▲"

        # Sweep marker
        annotations.append(dict(
            x=sig.timestamp, y=sig.sweep_price,
            xref="x", yref="y",
            text=f"<b>SWEEP {sym_arrow}</b>",
            showarrow=True, arrowhead=2,
            arrowcolor=COLORS["sweep"],
            font=dict(color=COLORS["sweep"], size=11, family="monospace"),
            ay=-30 if sig.direction == "SELL" else 30,
        ))

        # BOS marker
        annotations.append(dict(
            x=sig.timestamp, y=sig.bos_price,
            xref="x", yref="y",
            text="<b>BOS</b>",
            showarrow=True, arrowhead=1,
            arrowcolor=COLORS["bos"],
            font=dict(color=COLORS["bos"], size=10),
            ay=30 if sig.direction == "SELL" else -30,
        ))

        # OTE Fibonacci levels
        for entry_data in sig.entries:
            lvl = entry_data["level"]
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=sig.timestamp, x1=plot_df.index[-1],
                y0=entry_data["entry"], y1=entry_data["entry"],
                line=dict(color=col, width=1.5, dash="dashdot"),
                opacity=0.8,
            ))
            annotations.append(dict(
                x=plot_df.index[-1], y=entry_data["entry"],
                xref="x", yref="y",
                text=f"OTE {lvl} | 1:{entry_data['rr']}R",
                showarrow=False,
                font=dict(color=col, size=9),
                xanchor="right",
            ))

        # Filled trades from this signal
        sig_trades = [t for t in trades if
                      t["entry_time"] and t["entry_time"] >= sig.timestamp
                      and t["direction"] == sig.direction]
        for t in sig_trades[:3]:
            t_col = COLORS["win_bar"] if t["result"] == "WIN" else COLORS["loss_bar"]
            if t["entry_time"] and t["exit_time"]:
                shapes.append(dict(
                    type="rect", xref="x", yref="y",
                    x0=t["entry_time"], x1=t["exit_time"],
                    y0=min(t["entry"], t["exit_price"]),
                    y1=max(t["entry"], t["exit_price"]),
                    fillcolor=t_col, opacity=0.25,
                    line_color=t_col, line_width=1,
                ))

    fig.update_layout(
        shapes=shapes, annotations=annotations,
        title=dict(text=f"<b>Phase-404 — {symbol} | Asian Sweep → BOS → OTE</b>",
                   font=dict(size=18, color="white")),
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=550,
        margin=dict(l=60, r=120, t=60, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return fig


# ── Summary Figures ─────────────────────────────────────────────────────────

def draw_equity_curve(all_trades: list[dict]) -> go.Figure:
    fig = go.Figure()
    for symbol in SYMBOLS:
        sym_trades = sorted(
            [t for t in all_trades if t["symbol"] == symbol and t["entry_time"]],
            key=lambda x: x["entry_time"],
        )
        if not sym_trades:
            continue
        balance, times, balances = ACCOUNT_SIZE, [], []
        for t in sym_trades:
            balance += t["pnl_usd"]
            times.append(t["exit_time"])
            balances.append(round(balance, 2))

        fig.add_trace(go.Scatter(
            x=times, y=balances, name=symbol,
            mode="lines+markers", line=dict(width=2),
        ))

    fig.add_hline(y=ACCOUNT_SIZE, line_dash="dot", line_color="gray",
                  annotation_text="Starting Balance", annotation_position="right")
    fig.update_layout(
        title="<b>Equity Curve — All Symbols</b>",
        yaxis_title="Balance ($)", template="plotly_dark",
        height=350, margin=dict(l=60, r=40, t=50, b=40),
    )
    return fig


def draw_winrate_by_level(all_trades: list[dict]) -> go.Figure:
    data = {}
    for lvl in OTE_LEVELS:
        lvl_trades = [t for t in all_trades if abs(t["ote_level"] - lvl) < 0.01]
        total = len(lvl_trades)
        wins  = sum(1 for t in lvl_trades if t["result"] == "WIN")
        data[f"OTE {lvl}"] = {
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "total":    total,
            "wins":     wins,
        }

    labels = list(data.keys())
    win_rates = [data[l]["win_rate"] for l in labels]
    totals    = [data[l]["total"] for l in labels]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=labels, y=win_rates,
        marker_color=[COLORS["win_bar"], COLORS["equity"], COLORS["buy_entry"]],
        name="Win Rate %", text=[f"{w}%" for w in win_rates], textposition="outside",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=totals, name="Total Trades",
        mode="lines+markers+text", text=totals, textposition="top center",
        line=dict(color="white", dash="dot"),
    ), secondary_y=True)

    fig.update_layout(
        title="<b>Win Rate & Trade Count by OTE Level</b>",
        yaxis_title="Win Rate %", template="plotly_dark",
        height=350, margin=dict(l=60, r=60, t=50, b=40),
        yaxis=dict(range=[0, 100]),
    )
    fig.update_yaxes(title_text="Trade Count", secondary_y=True)
    return fig


def draw_pnl_distribution(all_trades: list[dict]) -> go.Figure:
    wins   = [t["pnl_usd"] for t in all_trades if t["result"] == "WIN"]
    losses = [t["pnl_usd"] for t in all_trades if t["result"] == "LOSS"]

    fig = go.Figure()
    if wins:
        fig.add_trace(go.Histogram(x=wins, name="WIN", marker_color=COLORS["win_bar"],
                                   opacity=0.75, nbinsx=15))
    if losses:
        fig.add_trace(go.Histogram(x=losses, name="LOSS", marker_color=COLORS["loss_bar"],
                                   opacity=0.75, nbinsx=15))
    fig.add_vline(x=0, line_dash="dash", line_color="white")
    fig.update_layout(
        title="<b>P&L Distribution</b>", barmode="overlay",
        xaxis_title="P&L ($)", yaxis_title="Frequency",
        template="plotly_dark", height=350,
        margin=dict(l=60, r=40, t=50, b=40),
    )
    return fig


def draw_stats_table(all_trades: list[dict]) -> go.Figure:
    rows = []
    for symbol in SYMBOLS:
        sym_t = [t for t in all_trades if t["symbol"] == symbol]
        if not sym_t:
            continue
        total  = len(sym_t)
        wins   = sum(1 for t in sym_t if t["result"] == "WIN")
        net    = round(sum(t["pnl_usd"] for t in sym_t), 2)
        avg_rr = round(np.mean([t["rr_target"] for t in sym_t if t["result"] == "WIN"]) if wins else 0, 2)
        wr     = round(wins / total * 100, 1) if total else 0
        rows.append([symbol, total, wins, total - wins, f"{wr}%", f"${net}", f"1:{avg_rr}"])

    # Totals row
    total_all  = len(all_trades)
    wins_all   = sum(1 for t in all_trades if t["result"] == "WIN")
    net_all    = round(sum(t["pnl_usd"] for t in all_trades), 2)
    wr_all     = round(wins_all / total_all * 100, 1) if total_all else 0
    rows.append(["TOTAL", total_all, wins_all, total_all - wins_all,
                 f"{wr_all}%", f"${net_all}", "—"])

    headers = ["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Net P&L", "Avg R:R"]
    colors  = []
    for r in rows:
        pnl = float(str(r[5]).replace("$", ""))
        colors.append("#00C853" if pnl >= 0 else "#FF1744")

    fig = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{h}</b>" for h in headers],
            fill_color="#1a1a2e", font=dict(color="white", size=13),
            align="center", height=36,
        ),
        cells=dict(
            values=list(zip(*rows)),
            fill_color=[["#0d0d1a"] * len(rows)],
            font=dict(color=["white"] * (len(rows) - 1) + ["#FFD700"],
                      size=12),
            align="center", height=30,
        ),
    ))
    fig.update_layout(
        title="<b>Phase-404 Backtest Summary</b>",
        template="plotly_dark", height=280,
        margin=dict(l=20, r=20, t=50, b=10),
    )
    return fig


# ── Master Report ─────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 60)
    print("  Phase-404 Backtest — Asian Sweep + BOS + OTE")
    print("=" * 60)

    all_trades: list[dict] = []
    symbol_signals = {}
    symbol_dfs     = {}

    for symbol in SYMBOLS:
        print(f"\n[{symbol}] Fetching data...", end=" ")
        df = fetch(symbol)
        if df.empty:
            print("NO DATA")
            continue
        print(f"{len(df)} candles")

        print(f"[{symbol}] Generating signals...", end=" ")
        signals = generate_signals(df, symbol)
        print(f"{len(signals)} setups found")

        if not signals:
            continue

        print(f"[{symbol}] Simulating trades across all OTE levels...", end=" ")
        trades = simulate_all_levels(df, signals, symbol)
        wins   = sum(1 for t in trades if t["result"] == "WIN")
        total  = len(trades)
        print(f"{total} trades | WR={round(wins/total*100,1) if total else 0}%")

        all_trades.extend(trades)
        symbol_signals[symbol] = signals
        symbol_dfs[symbol]     = df

    if not all_trades:
        print("\nNo trades generated. Check data availability.")
        return

    # ── Build HTML Report ────────────────────────────────────────────────────
    print("\n[Report] Building charts...")
    all_figs = []

    # Per-symbol candlestick charts
    for symbol, signals in symbol_signals.items():
        sym_trades = [t for t in all_trades if t["symbol"] == symbol]
        fig = draw_signal_chart(symbol_dfs[symbol], signals, sym_trades, symbol)
        all_figs.append(("chart", symbol, fig))

    # Summary charts
    all_figs.append(("equity",  "All",     draw_equity_curve(all_trades)))
    all_figs.append(("winrate", "By Level", draw_winrate_by_level(all_trades)))
    all_figs.append(("pnl",    "Dist",     draw_pnl_distribution(all_trades)))
    all_figs.append(("stats",  "Table",    draw_stats_table(all_trades)))

    # Write HTML
    html_parts = ["""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Phase-404 Backtest Report</title>
<style>
  body { background: #0a0a0f; color: #eee; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
  h1   { color: #00D4AA; border-bottom: 2px solid #00D4AA; padding-bottom: 10px; }
  h2   { color: #6495ED; margin-top: 40px; }
  .section { margin-bottom: 30px; background: #0d0d1a; border-radius: 10px; padding: 10px; }
  .strategy-box {
    background: #0d0d1a; border: 1px solid #6495ED;
    border-radius: 10px; padding: 20px; margin-bottom: 30px;
    font-family: monospace; font-size: 14px; line-height: 1.8;
  }
  .tag { background: #1a1a3e; border-radius: 4px; padding: 2px 8px; color: #FFD700; margin: 0 4px; }
</style>
</head>
<body>
<h1>Phase-404 Strategy — Backtest Report</h1>
<div class="strategy-box">
  <b style="color:#00D4AA; font-size:16px;">Strategy Rules</b><br><br>
  <b>Step 1:</b> Mark Asian session high/low <span class="tag">20:00–00:00 EST = 01:00–05:00 UTC</span><br>
  <b>Step 2:</b> Wait for liquidity sweep of Asian high <i>or</i> low<br>
  <b>Step 3:</b> Confirm Break of Structure (BOS) on M1 after sweep<br>
  <b>Step 4:</b> Place OTE limit orders at Fibonacci retracement levels:<br>
  &nbsp;&nbsp;&nbsp;&nbsp;<span class="tag">0.50</span> entry → <b>1:2 R:R</b> &nbsp;|&nbsp;
  <span class="tag">0.618</span> entry → <b>1:3 R:R</b> &nbsp;|&nbsp;
  <span class="tag">0.75</span> entry → <b>1:4 R:R</b>
</div>
"""]

    for kind, label, fig in all_figs:
        html_parts.append(f'<div class="section">')
        html_parts.append(fig.to_html(full_html=False, include_plotlyjs="cdn" if html_parts.__len__() < 3 else False))
        html_parts.append('</div>')

    html_parts.append("</body></html>")

    out_file = OUT_DIR / "phase404_report.html"
    out_file.write_text("\n".join(html_parts))

    print(f"\n[Report] Saved → {out_file}")
    print(f"\n{'='*60}")
    print(f"  TOTAL TRADES : {len(all_trades)}")
    wins  = sum(1 for t in all_trades if t["result"] == "WIN")
    total = len(all_trades)
    print(f"  WIN RATE     : {round(wins/total*100,1) if total else 0}%")
    net   = round(sum(t['pnl_usd'] for t in all_trades), 2)
    print(f"  NET P&L      : ${net}")
    print(f"{'='*60}\n")

    # Open in browser
    import webbrowser
    webbrowser.open(str(out_file))
    return all_trades


if __name__ == "__main__":
    run()
