"""
ForgeX AI — Streamlit Dashboard
Tabs: Backtest | Prop Firm Simulator | Live Dashboard
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import random
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import date, timedelta

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ForgeX AI Trading Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Strategy catalogue ─────────────────────────────────────────────────────────
STRATEGIES = {
    "S-01": "ICT Order Block + FVG",
    "S-02": "EMA Crossover + RSI",
    "S-03": "SMC BOS / ChoCH",
    "S-04": "VWAP Rejection",
    "S-05": "London Breakout",
    "S-06": "NAS100-US30 Correlation",
    "S-07": "Keltner Channel Squeeze",
    "S-08": "ICT Killzone (Asian OB)",
    "S-09": "MACD + RSI Divergence",
    "S-10": "Heikin-Ashi Trend",
}

IMPLEMENTED_STRATEGIES = {"S-01", "S-02", "S-03", "S-04", "S-05", "S-07", "S-09", "S-10"}

INSTRUMENTS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "NAS100", "US30", "SPX500", "XAUUSD", "XAGUSD", "USDCHF",
]

PROP_FIRMS = ["FundedNext", "FXIFY", "FundingPips", "E8Markets", "FTMO", "The5ers"]

TIMEFRAMES = ["1min", "5min", "15min", "1h", "1d"]

TF_LABELS = {
    "1min":  "1 Min  (proxied to 5m)",
    "5min":  "5 Min",
    "15min": "15 Min",
    "1h":    "1 Hour",
    "1d":    "Daily",
}

ACCOUNT_SIZES = {
    "$1,000 (Cents)":   1_000,
    "$5,000":           5_000,
    "$10,000":         10_000,
    "$25,000":         25_000,
    "$50,000":         50_000,
    "$100,000":       100_000,
    "$200,000":       200_000,
}

RULES_PATH = Path(__file__).parent.parent / "knowledge_base" / "prop_firms" / "rules.json"


def _load_rules() -> dict:
    with open(RULES_PATH) as f:
        return json.load(f)


def _get_firm_rules(firm_name: str) -> dict:
    data = _load_rules()
    key = firm_name.lower()
    for k, v in data.items():
        if isinstance(v, dict) and (k.lower() == key or key in k.lower()):
            return v
    return {"daily_dd_pct": 5.0, "max_dd_pct": 10.0}


# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: #1a1d27;
        border: 1px solid #2d3147;
        border-radius: 10px;
        padding: 16px 20px;
        margin: 4px 0;
    }
    .metric-val   { font-size: 1.6rem; font-weight: 700; }
    .metric-label { font-size: 0.82rem; color: #7c8ba1; margin-top: 2px; }
    .green  { color: #00d4aa; }
    .red    { color: #ff4b4b; }
    .orange { color: #ffa500; }
    .stage-badge {
        display: inline-block; padding: 3px 10px;
        border-radius: 20px; font-size: 0.78rem; font-weight: 600;
    }
    .stage-funded { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa55; }
    .stage-failed { background:#ff4b4b22; color:#ff4b4b; border:1px solid #ff4b4b55; }
    .stage-active { background:#ffa50022; color:#ffa500; border:1px solid #ffa50055; }
    div[data-testid="stSidebar"] { background: #13151f; }
    .strat-label { font-size: 0.8rem; color: #7c8ba1; margin-left: 4px; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("# ⚡ ForgeX AI")
    st.markdown("*AGI-Powered Trading Bot*")
    st.divider()

    st.markdown("### Strategies")
    selected_strategies = []
    for sid, sname in STRATEGIES.items():
        implemented = sid in IMPLEMENTED_STRATEGIES
        label = f"**{sid}** — {sname}" + ("" if implemented else " *(coming soon)*")
        checked = st.checkbox(
            label,
            value=(sid in ["S-01", "S-02", "S-03"] and implemented),
            key=f"strat_{sid}",
            disabled=not implemented,
        )
        if checked and implemented:
            selected_strategies.append(sid)

    st.divider()

    st.markdown("### Instruments")
    selected_instruments = st.multiselect(
        "Select pairs / indices",
        INSTRUMENTS,
        default=["EURUSD", "NAS100", "US30"],
    )

    st.divider()

    st.markdown("### Prop Firm")
    selected_firm  = st.selectbox("Firm", PROP_FIRMS)
    selected_stage = st.selectbox("Stage", ["STAGE1", "STAGE2", "FUNDED"])

    st.divider()

    st.markdown("### Account")
    account_label = st.selectbox("Account Size", list(ACCOUNT_SIZES.keys()), index=4)
    account_size  = ACCOUNT_SIZES[account_label]
    is_cents      = "Cents" in account_label
    if is_cents:
        st.info("Cents account — lot sizes and P&L scaled to micro units.")
    risk_pct = st.slider("Risk per Trade %", 0.5, 3.0, 1.0, 0.25)

    st.divider()

    st.markdown("### Settings")
    tf_label = st.selectbox(
        "Timeframe",
        list(TF_LABELS.values()),
        index=3,   # default 1h
    )
    tf = [k for k, v in TF_LABELS.items() if v == tf_label][0]
    if tf == "1min":
        st.caption("yfinance 1m limit is 7 days — using 5m data as proxy.")

    st.divider()
    st.markdown(
        "<div style='color:#7c8ba1;font-size:0.75rem'>"
        "ForgeX AI v1.0 · Powered by Claude<br>"
        "© 2025 ForgeX Systems</div>",
        unsafe_allow_html=True,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _metric(label: str, value: str, color: str = ""):
    cls = f"metric-val {color}" if color else "metric-val"
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="{cls}">{value}</div>'
        f'<div class="metric-label">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _pnl_style(val):
    if isinstance(val, (int, float)):
        return "color: #00d4aa" if val >= 0 else "color: #ff4b4b"
    return ""


def _result_style(val):
    if val == "WIN":     return "color: #00d4aa"
    if val == "LOSS":    return "color: #ff4b4b"
    if val == "BLOCKED": return "color: #888888"
    return ""


def _wr_color(wr: float) -> str:
    return "green" if wr >= 60 else "orange" if wr >= 50 else "red"


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_bt, tab_sim, tab_live = st.tabs([
    "📊  Backtest",
    "🏦  Prop Firm Simulator",
    "🟢  Live Dashboard",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
with tab_bt:
    st.markdown("## Strategy Backtesting")

    if not selected_strategies:
        st.warning("Select at least one strategy in the sidebar.")
    elif not selected_instruments:
        st.warning("Select at least one instrument in the sidebar.")
    else:
        st.markdown(
            f"**{len(selected_strategies)} strategy/ies** × "
            f"**{len(selected_instruments)} instrument(s)** | "
            f"TF: **{tf}** | Firm rules: **{selected_firm}** | "
            f"Account: **{account_label}** | Risk: **{risk_pct}%**"
        )

    run_bt = st.button(
        "▶  Run Backtest",
        type="primary",
        key="run_bt",
        disabled=not (selected_strategies and selected_instruments),
    )

    if run_bt:
        from backtest.data_fetcher import fetch_ohlc
        from backtest.signals import run_strategy
        from backtest.engine import BacktestEngine, BacktestResult
        from backtest.report import (
            equity_curve_chart, summary_table,
            trades_table, win_rate_by_strategy_chart, drawdown_chart,
        )

        firm_rules_dict = _get_firm_rules(selected_firm)
        engine_rules = {
            "daily_dd_pct": firm_rules_dict.get("daily_dd_pct") or 5.0,
            "max_dd_pct":   firm_rules_dict.get("max_dd_pct") or 10.0,
        }

        results: list[BacktestResult] = []
        errors: list[str] = []

        progress = st.progress(0, text="Fetching data…")
        total_jobs = len(selected_strategies) * len(selected_instruments)
        job = 0

        for sym in selected_instruments:
            df = fetch_ohlc(sym, tf, days=365)
            if df is None or df.empty:
                errors.append(f"No data returned for **{sym}** on {tf} timeframe.")
                job += len(selected_strategies)
                progress.progress(min(job / total_jobs, 1.0))
                continue

            for sid in selected_strategies:
                job += 1
                progress.progress(
                    min(job / total_jobs, 1.0),
                    text=f"Running {sid} ({STRATEGIES[sid]}) on {sym}…"
                )
                try:
                    sigs = run_strategy(sid, df, sym)
                    engine = BacktestEngine(
                        account_size       = account_size,
                        risk_per_trade_pct = risk_pct,
                        prop_firm_rules    = engine_rules,
                        stage              = selected_stage,
                    )
                    res = engine.run(df, sigs, sid, sym, tf, selected_firm)
                    results.append(res)
                except ValueError as e:
                    errors.append(f"{sid}/{sym}: {e}")
                except Exception as e:
                    errors.append(f"{sid}/{sym}: {type(e).__name__}: {e}")

        progress.empty()
        st.session_state["bt_results"] = results
        st.session_state["bt_errors"]  = errors

    results = st.session_state.get("bt_results", [])
    errors  = st.session_state.get("bt_errors",  [])

    if errors:
        with st.expander(f"⚠ {len(errors)} warning(s)", expanded=len(results) == 0):
            for e in errors:
                st.warning(e)

    if results:
        from backtest.report import (
            summary_table, trades_table,
            equity_curve_chart, drawdown_chart, win_rate_by_strategy_chart,
        )

        closed_all   = sum(r.total_trades for r in results)
        wins_all     = sum(r.wins for r in results)
        blocked_all  = sum(r.blocked_trades for r in results)
        net_pnl_all  = sum(r.net_pnl_usd for r in results)
        avg_wr       = sum(r.win_rate for r in results) / len(results) if results else 0
        max_dd       = max((r.max_drawdown_pct for r in results), default=0)

        st.markdown("### Overall Summary")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: _metric("Total Trades",  str(closed_all))
        with c2: _metric("Avg Win Rate",  f"{avg_wr:.1f}%", _wr_color(avg_wr))
        with c3: _metric("Net P&L",       f"${net_pnl_all:+,.0f}",
                          "green" if net_pnl_all >= 0 else "red")
        with c4: _metric("Max DD %",      f"{max_dd:.2f}%",
                          "green" if max_dd < 5 else "orange" if max_dd < 8 else "red")
        with c5: _metric("Combos Run",    str(len(results)))
        with c6: _metric("Blocked",       str(blocked_all))

        st.markdown("---")
        st.markdown("### Strategy Comparison")
        df_sum = summary_table(results)
        st.dataframe(
            df_sum.style
                .map(_pnl_style, subset=["Net P&L $"])
                .format({
                    "Win Rate %": "{:.1f}",
                    "Net P&L $":  "${:,.2f}",
                    "Net P&L %":  "{:.2f}%",
                    "Max DD %":   "{:.2f}%",
                    "Avg R:R":    "{:.2f}",
                    "Profit Factor": "{:.2f}",
                }),
            use_container_width=True,
            height=min(80 + len(df_sum) * 38, 400),
        )

        # Charts
        best = max(results, key=lambda r: r.win_rate)
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(win_rate_by_strategy_chart(results), use_container_width=True)
        with col_r:
            st.plotly_chart(equity_curve_chart(best), use_container_width=True)

        st.plotly_chart(drawdown_chart(best), use_container_width=True)

        # Trade log
        st.markdown("### Trade Log")
        labels = [f"{r.strategy} — {STRATEGIES.get(r.strategy, r.strategy)} / {r.symbol}"
                  for r in results]
        sel = st.selectbox("View trades for", labels, key="bt_trade_sel")
        sel_idx = labels.index(sel)
        df_t = trades_table(results[sel_idx])
        st.dataframe(
            df_t.style
                .map(_result_style, subset=["Result"])
                .map(_pnl_style,    subset=["P&L $"]),
            use_container_width=True,
            height=400,
        )

    elif not run_bt:
        st.info("Configure options in the sidebar then click **▶ Run Backtest**.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROP FIRM SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sim:
    st.markdown("## Prop Firm Challenge Simulator")

    if not selected_strategies:
        st.warning("Select at least one strategy in the sidebar.")
    elif not selected_instruments:
        st.warning("Select at least one instrument in the sidebar.")
    else:
        firm_data = _get_firm_rules(selected_firm)
        p1  = firm_data.get("p1_target_pct",      "—")
        p2  = firm_data.get("p2_target_pct",       "—")
        ddd = firm_data.get("daily_dd_pct",         5)
        mdd = firm_data.get("max_dd_pct",          "trailing")

        st.markdown(
            f"**{selected_firm}** | Stage 1 target: **{p1}%** | "
            f"Stage 2 target: **{p2}%** | Daily DD limit: **{ddd}%** | "
            f"Max DD: **{mdd}%** | Account: **{account_label}**"
        )

    col_a, col_b = st.columns([1, 1])
    with col_a:
        run_single = st.button(
            f"▶  Simulate {selected_firm}",
            type="primary",
            key="run_sim_single",
            disabled=not (selected_strategies and selected_instruments),
        )
    with col_b:
        run_all_firms = st.button(
            "▶  Run All 6 Firms",
            key="run_sim_all",
            disabled=not (selected_strategies and selected_instruments),
        )

    if run_single or run_all_firms:
        from simulator.prop_sim import PropFirmSimulator, SimResult

        firms_to_run = PROP_FIRMS if run_all_firms else [selected_firm]
        sim_results: list = []
        sim_errors: list  = []

        prog = st.progress(0, text="Starting simulation…")
        for i, firm in enumerate(firms_to_run):
            prog.progress((i + 1) / len(firms_to_run), text=f"Simulating {firm}…")
            try:
                sim = PropFirmSimulator(
                    firm_name          = firm,
                    account_size       = account_size,
                    strategies         = selected_strategies,
                    symbols            = selected_instruments,
                    timeframe          = tf,
                    risk_per_trade_pct = risk_pct,
                )
                res = sim.run()
                sim_results.append(res)
            except Exception as e:
                sim_errors.append(f"**{firm}**: {type(e).__name__}: {e}")

        prog.empty()
        st.session_state["sim_results"] = sim_results
        st.session_state["sim_errors"]  = sim_errors

    sim_results: list = st.session_state.get("sim_results", [])
    sim_errors:  list = st.session_state.get("sim_errors",  [])

    if sim_errors:
        with st.expander(f"⚠ {len(sim_errors)} error(s)"):
            for e in sim_errors:
                st.error(e)

    if sim_results:
        # Firm result cards
        st.markdown("### Results by Firm")
        card_cols = st.columns(min(len(sim_results), 3))
        for idx, res in enumerate(sim_results):
            col = card_cols[idx % 3]
            with col:
                stage_css = (
                    "stage-funded" if res.stage_reached == "FUNDED" else
                    "stage-failed" if res.stage_reached == "FAILED" else
                    "stage-active"
                )
                st.markdown(
                    f"**{res.firm_name}**  "
                    f'<span class="stage-badge {stage_css}">{res.stage_reached}</span>',
                    unsafe_allow_html=True,
                )
                pnl_delta = f"{res.net_pnl_pct:+.2f}%"
                st.metric("Balance",  f"${res.final_balance:,.0f}", pnl_delta)
                st.metric("Win Rate", f"{res.win_rate:.1f}%")
                st.metric("Max DD",   f"{res.max_dd_pct:.2f}%")
                if res.failed_reason:
                    st.caption(f"❌ {res.failed_reason}")
                st.markdown("---")

        # Comparison table
        st.markdown("### Firm Comparison")
        cmp_rows = []
        for r in sim_results:
            cmp_rows.append({
                "Firm":          r.firm_name,
                "Stage Reached": r.stage_reached,
                "Final Balance": round(r.final_balance, 2),
                "Net P&L $":     r.net_pnl_usd,
                "Net P&L %":     r.net_pnl_pct,
                "Win Rate %":    r.win_rate,
                "Max DD %":      r.max_dd_pct,
                "Trades":        r.total_trades,
                "Blocked":       r.blocked,
                "Profit Factor": r.profit_factor,
                "Trading Days":  r.trading_days,
            })
        df_cmp = pd.DataFrame(cmp_rows)
        st.dataframe(
            df_cmp.style
                .map(_pnl_style, subset=["Net P&L $", "Net P&L %"])
                .format({
                    "Final Balance":  "${:,.0f}",
                    "Net P&L $":      "${:+,.0f}",
                    "Net P&L %":      "{:+.2f}%",
                    "Win Rate %":     "{:.1f}%",
                    "Max DD %":       "{:.2f}%",
                    "Profit Factor":  "{:.2f}",
                }),
            use_container_width=True,
        )

        # Detail panel for one firm
        st.markdown("### Firm Detail")
        sel_firm_name = st.selectbox(
            "Select firm", [r.firm_name for r in sim_results], key="sim_firm_detail"
        )
        sel_sim = next(r for r in sim_results if r.firm_name == sel_firm_name)

        # Stage history
        if sel_sim.stage_history:
            st.markdown("**Stage Progression**")
            st.dataframe(pd.DataFrame(sel_sim.stage_history), use_container_width=True)

        # Equity curve
        closed_trades = [t for t in sel_sim.trades if t.result in ("WIN", "LOSS", "BE")]
        if closed_trades:
            bal = account_size
            curve = []
            for t in closed_trades:
                bal += t.pnl_usd
                curve.append({"#": t.trade_id, "balance": bal,
                               "result": t.result, "stage": t.stage})
            df_curve = pd.DataFrame(curve)
            colors = ["#00d4aa" if r == "WIN" else "#ff4b4b" for r in df_curve["result"]]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_curve["#"], y=df_curve["balance"],
                mode="lines+markers",
                line=dict(color="#00d4aa", width=2),
                fill="tozeroy", fillcolor="rgba(0,212,170,0.08)",
                marker=dict(color=colors, size=5),
                name="Balance",
            ))
            fig.add_hline(y=account_size, line_dash="dash",
                          line_color="gray", annotation_text="Start")
            fig.update_layout(
                title=f"{sel_firm_name} — Equity Curve",
                template="plotly_dark", height=320,
                xaxis_title="Trade #", yaxis_title="Balance ($)",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Trade log
        st.markdown("**Trade Log**")
        if sel_sim.trades:
            df_log = pd.DataFrame([{
                "#":        t.trade_id,
                "Strategy": f"{t.strategy} — {STRATEGIES.get(t.strategy, t.strategy)}",
                "Symbol":   t.symbol,
                "Dir":      t.direction,
                "Entry":    round(t.entry_price, 5),
                "SL":       round(t.sl_price, 5),
                "TP":       round(t.tp_price, 5),
                "R:R":      round(t.risk_rr, 2),
                "Lot":      t.lot_size,
                "Result":   t.result,
                "P&L $":    t.pnl_usd,
                "Stage":    t.stage,
                "Daily DD%": t.daily_dd_pct,
                "Blocked":  t.block_reason or "",
            } for t in sel_sim.trades])
            st.dataframe(
                df_log.style
                    .map(_result_style, subset=["Result"])
                    .map(_pnl_style,    subset=["P&L $"]),
                use_container_width=True,
                height=400,
            )

    elif not (run_single or run_all_firms):
        st.info("Configure the sidebar then click **▶ Simulate** to run the challenge.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_live:
    st.markdown("## Live Trading Dashboard")

    h1, h2, h3 = st.columns([3, 1, 1])
    with h1:
        api_url = st.text_input("API URL", value="http://localhost:8000", key="api_url")
    with h2:
        refresh = st.button("🔄 Refresh", key="live_refresh")
    with h3:
        auto_ref = st.checkbox("Auto 30s", key="auto_ref")

    dashboard_data = trades_data = agents_data = None
    api_ok = False

    try:
        import requests as req
        r1 = req.get(f"{api_url}/dashboard",    timeout=2)
        r2 = req.get(f"{api_url}/trades/today", timeout=2)
        r3 = req.get(f"{api_url}/agents/status", timeout=2)
        if r1.ok:
            dashboard_data = r1.json(); api_ok = True
        if r2.ok: trades_data = r2.json()
        if r3.ok: agents_data = r3.json()
    except Exception:
        pass

    if not api_ok:
        st.info(
            "API server not reachable — showing demo values.  \n"
            "Start it with:  `python app.py`"
        )
        dashboard_data = {
            "balance": 100_420.50, "equity": 100_420.50,
            "daily_pnl": 420.50,   "daily_dd_pct": 0.18,
            "total_dd_pct": 0.21,  "open_trades": 0,
            "session": "London",   "active_firm": selected_firm,
            "stage": selected_stage, "win_rate_today": 66.7,
            "trades_today": 3,     "wins_today": 2,
        }
        agents_data = {f"agent_0{i}": "IDLE" for i in range(1, 9)}
        trades_data = []

    if dashboard_data:
        st.markdown("### Account Health")
        a1, a2, a3, a4, a5, a6 = st.columns(6)
        dpnl = dashboard_data.get("daily_pnl", 0)
        ddd  = dashboard_data.get("daily_dd_pct", 0)
        tdd  = dashboard_data.get("total_dd_pct", 0)
        wr   = dashboard_data.get("win_rate_today", 0)
        with a1: _metric("Balance",     f"${dashboard_data.get('balance', 0):,.2f}")
        with a2: _metric("Daily P&L",   f"${dpnl:+,.2f}", "green" if dpnl >= 0 else "red")
        with a3: _metric("Daily DD %",  f"{ddd:.3f}%",
                          "green" if ddd < 2 else "orange" if ddd < 4 else "red")
        with a4: _metric("Total DD %",  f"{tdd:.3f}%",
                          "green" if tdd < 4 else "orange" if tdd < 7 else "red")
        with a5: _metric("Open Trades", str(dashboard_data.get("open_trades", 0)))
        with a6: _metric("Win Rate",    f"{wr:.1f}%", _wr_color(wr))

        st.markdown("---")

        info_col, agent_col = st.columns(2)
        with info_col:
            st.markdown("### Session")
            st.markdown(
                f"**Firm:** {dashboard_data.get('active_firm', '—')}  |  "
                f"**Stage:** {dashboard_data.get('stage', '—')}  |  "
                f"**Session:** {dashboard_data.get('session', '—')}"
            )
            st.markdown(
                f"Trades today: **{dashboard_data.get('trades_today', 0)}**  "
                f"({dashboard_data.get('wins_today', 0)} wins)"
            )

        with agent_col:
            st.markdown("### Agents")
            AGENT_NAMES = {
                "agent_01": "News Sentinel",  "agent_02": "Signal Hunter",
                "agent_03": "Strategy Oracle","agent_04": "Risk Enforcer",
                "agent_05": "Executor",       "agent_06": "Recorder",
                "agent_07": "Forecaster",     "agent_08": "Orchestrator",
            }
            if agents_data:
                acols = st.columns(4)
                for i, (aid, aname) in enumerate(AGENT_NAMES.items()):
                    status = agents_data.get(aid, "IDLE")
                    icon = "🟢" if status == "RUNNING" else "⚪"
                    acols[i % 4].markdown(f"{icon} **{aid[-2:]}**  \n{aname}")

        st.markdown("---")
        st.markdown("### Today's Trades")
        if trades_data:
            rows = trades_data if isinstance(trades_data, list) else [trades_data]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=300)
        else:
            st.info("No trades recorded today.")

        st.markdown("### Bot Controls")
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("▶ Start Bot", type="primary"):
                try:
                    import requests as req
                    r = req.post(f"{api_url}/agents/start", timeout=5)
                    st.success("Bot started." if r.ok else f"Error: {r.text}")
                except Exception as e:
                    st.error(str(e))
        with b2:
            if st.button("⏹ Stop Bot"):
                try:
                    import requests as req
                    r = req.post(f"{api_url}/agents/stop", timeout=5)
                    st.success("Bot stopped." if r.ok else f"Error: {r.text}")
                except Exception as e:
                    st.error(str(e))
        with b3:
            mode = st.selectbox("Mode", ["📄 Paper (Virtual)", "💰 Live (Real)"], key="trade_mode")
            if "Live" in mode:
                st.error("Live mode sends real orders. Connect MT5 first.")

    if auto_ref:
        import time
        time.sleep(30)
        st.rerun()
