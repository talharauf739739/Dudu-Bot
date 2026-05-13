"""
Backtest report generator.
Builds Plotly charts and summary tables from BacktestResult.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from backtest.engine import BacktestResult


def equity_curve_chart(result: BacktestResult) -> go.Figure:
    curve = result.equity_curve()
    if not curve:
        return go.Figure().update_layout(title="No trades to display")

    df = pd.DataFrame(curve)
    colors = ["#00D4AA" if r == "WIN" else "#FF4B4B" for r in df["result"]]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7, 0.3],
                        subplot_titles=("Equity Curve", "Trade P&L"))

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["balance"],
        mode="lines+markers",
        line=dict(color="#00D4AA", width=2),
        fill="tozeroy", fillcolor="rgba(0,212,170,0.08)",
        name="Balance",
        marker=dict(color=colors, size=6),
    ), row=1, col=1)

    fig.add_hline(y=result.account_size, line_dash="dash",
                  line_color="gray", annotation_text="Start", row=1, col=1)

    # P&L bars
    pnls = [t.pnl_usd for t in result.closed_trades]
    times = [str(t.exit_time) for t in result.closed_trades]
    bar_colors = ["#00D4AA" if p >= 0 else "#FF4B4B" for p in pnls]
    fig.add_trace(go.Bar(x=times, y=pnls, marker_color=bar_colors, name="P&L"), row=2, col=1)

    fig.update_layout(
        title=f"{result.strategy} | {result.symbol} | {result.prop_firm} {result.stage}",
        template="plotly_dark",
        height=500,
        showlegend=False,
    )
    return fig


def drawdown_chart(result: BacktestResult) -> go.Figure:
    if not result.closed_trades:
        return go.Figure()
    dds = [t.total_dd_after for t in result.closed_trades]
    times = [str(t.exit_time) for t in result.closed_trades]
    limit = result.trades[0].total_dd_after if result.trades else 10

    # Get firm DD limit from result context
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=[-d for d in dds],
        fill="tozeroy", fillcolor="rgba(255,75,75,0.15)",
        line=dict(color="#FF4B4B"), name="Drawdown %"
    ))
    fig.update_layout(
        title="Drawdown Over Time",
        yaxis_title="Drawdown %",
        template="plotly_dark",
        height=250,
    )
    return fig


def summary_table(results: list[BacktestResult]) -> pd.DataFrame:
    """Build comparison table for multiple backtest results."""
    rows = []
    for r in results:
        rows.append({
            "Strategy":    r.strategy,
            "Symbol":      r.symbol,
            "TF":          r.timeframe,
            "Firm":        r.prop_firm,
            "Stage":       r.stage,
            "Trades":      r.total_trades,
            "Win Rate %":  r.win_rate,
            "Net P&L $":   r.net_pnl_usd,
            "Net P&L %":   r.net_pnl_pct,
            "Avg R:R":     r.avg_rr,
            "Max DD %":    r.max_drawdown_pct,
            "Blocked":     r.blocked_trades,
            "Profit Factor": r.profit_factor,
        })
    return pd.DataFrame(rows)


def trades_table(result: BacktestResult) -> pd.DataFrame:
    rows = []
    for t in result.trades:
        rows.append({
            "#":        t.trade_id,
            "Strategy": t.strategy,
            "Dir":      t.direction,
            "Entry":    t.entry_price,
            "SL":       t.sl_price,
            "TP":       t.tp_price,
            "R:R":      t.risk_rr,
            "Lot":      t.lot_size,
            "Result":   t.result,
            "P&L $":    t.pnl_usd,
            "P&L %":    t.pnl_pct,
            "Hold Bars":t.hold_bars,
            "DD After": t.daily_dd_after,
            "Blocked":  t.block_reason or "",
            "Entry Time": str(t.entry_time)[:16],
            "Exit Time":  str(t.exit_time)[:16] if t.exit_time else "",
        })
    return pd.DataFrame(rows)


def win_rate_by_strategy_chart(results: list[BacktestResult]) -> go.Figure:
    labels = [f"{r.strategy}\n{r.symbol}" for r in results]
    win_rates = [r.win_rate for r in results]
    colors = ["#00D4AA" if w >= 65 else "#FFA500" if w >= 55 else "#FF4B4B" for w in win_rates]

    fig = go.Figure(go.Bar(
        x=labels, y=win_rates,
        marker_color=colors,
        text=[f"{w:.1f}%" for w in win_rates],
        textposition="outside",
    ))
    fig.add_hline(y=65, line_dash="dash", line_color="#00D4AA",
                  annotation_text="65% target")
    fig.update_layout(
        title="Win Rate by Strategy",
        yaxis_title="Win Rate %",
        template="plotly_dark",
        height=350,
    )
    return fig
