"""
ForgeX AI — Streamlit Dashboard
Tabs: Backtest | Prop Firm Simulator | Live Dashboard
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ForgeX AI Trading Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Strategy catalogue ────────────────────────────────────────────────────────
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

INSTRUMENTS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "NAS100", "US30", "SPX500", "XAUUSD", "XAGUSD", "USDCHF",
]

PROP_FIRMS = [
    "FundedNext", "FXIFY", "FundingPips",
    "E8Markets", "FTMO", "The5ers",
]

TIMEFRAMES = ["5min", "15min", "1h", "4h", "1d"]

ACCOUNT_SIZES = {
    "$10,000":  10_000,
    "$25,000":  25_000,
    "$50,000":  50_000,
    "$100,000": 100_000,
    "$200,000": 200_000,
}


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
    .metric-val { font-size: 1.6rem; font-weight: 700; }
    .metric-label { font-size: 0.82rem; color: #7c8ba1; margin-top: 2px; }
    .green { color: #00d4aa; }
    .red   { color: #ff4b4b; }
    .orange { color: #ffa500; }
    .stage-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .stage-funded { background: #00d4aa22; color: #00d4aa; border: 1px solid #00d4aa55; }
    .stage-failed { background: #ff4b4b22; color: #ff4b4b; border: 1px solid #ff4b4b55; }
    .stage-active { background: #ffa50022; color: #ffa500; border: 1px solid #ffa50055; }
    div[data-testid="stSidebar"] { background: #13151f; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("# ⚡ ForgeX AI")
    st.markdown("*AGI-Powered Trading Bot*")
    st.divider()

    st.markdown("### Strategies")
    selected_strategies = []
    cols = st.columns(2)
    for i, (sid, sname) in enumerate(STRATEGIES.items()):
        col = cols[i % 2]
        if col.checkbox(f"{sid}", value=(sid in ["S-01", "S-02", "S-03"]),
                        key=f"strat_{sid}"):
            selected_strategies.append(sid)

    st.divider()

    st.markdown("### Instruments")
    selected_instruments = st.multiselect(
        "Select pairs/indices",
        INSTRUMENTS,
        default=["EURUSD", "NAS100", "US30"],
    )

    st.divider()

    st.markdown("### Prop Firm")
    selected_firm = st.selectbox("Firm", PROP_FIRMS)
    selected_stage = st.selectbox("Stage", ["STAGE1", "STAGE2", "FUNDED"])

    st.divider()

    st.markdown("### Account")
    account_label = st.selectbox("Account Size", list(ACCOUNT_SIZES.keys()),
                                 index=3)
    account_size = ACCOUNT_SIZES[account_label]
    risk_pct = st.slider("Risk per Trade %", 0.5, 3.0, 1.0, 0.25)

    st.divider()

    st.markdown("### Date Range")
    start_date = st.date_input("From", date.today() - timedelta(days=180))
    end_date   = st.date_input("To",   date.today())

    tf = st.selectbox("Timeframe", TIMEFRAMES, index=2)

    st.divider()
    st.markdown(
        "<div style='color:#7c8ba1;font-size:0.75rem'>"
        "ForgeX AI v1.0 · Built by Anthropic Claude<br>"
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


def _color_result(val):
    if val == "WIN":   return "color: #00d4aa"
    if val == "LOSS":  return "color: #ff4b4b"
    if val == "BLOCKED": return "color: #888"
    return ""


def _pnl_color(val):
    if isinstance(val, (int, float)):
        return "color: #00d4aa" if val >= 0 else "color: #ff4b4b"
    return ""


# ── Tab layout ────────────────────────────────────────────────────────────────
tab_bt, tab_sim, tab_live = st.tabs([
    "📊 Backtest",
    "🏦 Prop Firm Simulator",
    "🟢 Live Dashboard",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
with tab_bt:
    st.markdown("## Strategy Backtesting")
    st.markdown(
        f"Running **{len(selected_strategies)}** strategies on "
        f"**{', '.join(selected_instruments) or 'no instruments'}** | "
        f"TF: **{tf}** | "
        f"Period: **{start_date}** → **{end_date}**"
    )

    run_bt = st.button("▶ Run Backtest", type="primary", key="run_bt",
                       disabled=not (selected_strategies and selected_instruments))

    if run_bt:
        with st.spinner("Fetching data and running strategies..."):
            try:
                from backtest.data_fetcher import fetch_ohlc
                from backtest.signals import run_strategy
                from backtest.engine import BacktestEngine, BacktestResult
                from backtest.report import (equity_curve_chart, summary_table,
                                             trades_table, win_rate_by_strategy_chart,
                                             drawdown_chart)
                import json
                from pathlib import Path

                rules_path = Path(__file__).parent.parent / "knowledge_base" / "prop_firms" / "rules.json"
                with open(rules_path) as f:
                    all_rules = json.load(f)
                firm_rules_list = {
                    r["firm_name"].lower(): r for r in all_rules["prop_firms"]
                }
                firm_key = selected_firm.lower()
                firm_rules = next(
                    (v for k, v in firm_rules_list.items() if firm_key in k or k in firm_key),
                    {"daily_dd_pct": 5.0, "max_dd_pct": 10.0}
                )
                engine_rules = {
                    "daily_dd_pct": firm_rules.get("daily_dd_pct", 5.0),
                    "max_dd_pct":   firm_rules.get("max_dd_pct",
                                                   firm_rules.get("phase1_max_dd_pct", 10.0)),
                }

                results: list[BacktestResult] = []
                errors = []

                for sym in selected_instruments:
                    df = fetch_ohlc(sym, tf, period="1y")
                    if df is None or df.empty:
                        errors.append(f"No data: {sym}")
                        continue
                    for sid in selected_strategies:
                        try:
                            sigs = run_strategy(sid, df)
                            engine = BacktestEngine(
                                account_size       = account_size,
                                risk_per_trade_pct = risk_pct,
                                prop_firm_rules    = engine_rules,
                                stage              = selected_stage,
                            )
                            res = engine.run(df, sigs, sid, sym, tf, selected_firm)
                            results.append(res)
                        except NotImplementedError:
                            errors.append(f"{sid} not yet implemented")
                        except Exception as e:
                            errors.append(f"{sid}/{sym}: {e}")

                st.session_state["bt_results"] = results
                st.session_state["bt_errors"]  = errors

            except Exception as e:
                st.error(f"Backtest error: {e}")

    results = st.session_state.get("bt_results", [])
    errors  = st.session_state.get("bt_errors", [])

    if errors:
        with st.expander(f"⚠ {len(errors)} warning(s)"):
            for e in errors:
                st.warning(e)

    if results:
        # Summary metrics (aggregated)
        total_trades = sum(r.total_trades for r in results)
        total_wins   = sum(r.wins for r in results)
        total_blocked = sum(r.blocked_trades for r in results)
        net_pnl      = sum(r.net_pnl_usd for r in results)
        avg_wr       = sum(r.win_rate for r in results) / len(results)
        max_dd       = max(r.max_drawdown_pct for r in results)

        st.markdown("### Summary")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: _metric("Total Trades", str(total_trades))
        with c2: _metric("Win Rate", f"{avg_wr:.1f}%",
                          "green" if avg_wr >= 60 else "orange" if avg_wr >= 50 else "red")
        with c3: _metric("Net P&L", f"${net_pnl:+,.0f}",
                          "green" if net_pnl >= 0 else "red")
        with c4: _metric("Max DD %", f"{max_dd:.2f}%",
                          "green" if max_dd < 5 else "orange" if max_dd < 8 else "red")
        with c5: _metric("Strategies Run", str(len(results)))
        with c6: _metric("Blocked", str(total_blocked))

        st.markdown("---")

        # Comparison table
        st.markdown("### Strategy Comparison")
        from backtest.report import summary_table, win_rate_by_strategy_chart
        df_summary = summary_table(results)
        st.dataframe(
            df_summary.style
                .applymap(_pnl_color, subset=["Net P&L $"])
                .format({"Win Rate %": "{:.1f}", "Net P&L $": "${:,.2f}",
                         "Net P&L %": "{:.2f}%", "Max DD %": "{:.2f}%",
                         "Avg R:R": "{:.2f}", "Profit Factor": "{:.2f}"}),
            use_container_width=True,
            height=300,
        )

        # Charts row
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(win_rate_by_strategy_chart(results),
                            use_container_width=True)

        # Show equity curve for best result by win rate
        best = max(results, key=lambda r: r.win_rate)
        from backtest.report import equity_curve_chart, drawdown_chart
        with col_r:
            st.plotly_chart(equity_curve_chart(best), use_container_width=True)

        st.plotly_chart(drawdown_chart(best), use_container_width=True)

        # Per-result detail
        st.markdown("### Trade Log")
        sel_result_label = st.selectbox(
            "View trades for",
            [f"{r.strategy} / {r.symbol}" for r in results],
        )
        sel_idx = [f"{r.strategy} / {r.symbol}" for r in results].index(sel_result_label)
        from backtest.report import trades_table
        df_trades = trades_table(results[sel_idx])
        st.dataframe(
            df_trades.style.applymap(_color_result, subset=["Result"])
                           .applymap(_pnl_color, subset=["P&L $"]),
            use_container_width=True,
            height=400,
        )

    elif not run_bt:
        st.info("Select strategies and instruments in the sidebar, then click **Run Backtest**.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROP FIRM SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sim:
    st.markdown("## Prop Firm Challenge Simulator")
    st.markdown(
        f"Simulating **{selected_firm}** challenge with "
        f"**{account_label}** account | Risk: **{risk_pct}%** per trade"
    )

    col_sim, col_all = st.columns([1, 1])
    with col_sim:
        run_single = st.button(f"▶ Simulate {selected_firm}", type="primary",
                               key="run_sim_single",
                               disabled=not (selected_strategies and selected_instruments))
    with col_all:
        run_all = st.button("▶ Run All 6 Firms", key="run_sim_all",
                            disabled=not (selected_strategies and selected_instruments))

    if run_single or run_all:
        from simulator.prop_sim import PropFirmSimulator, run_all_firms, SimResult

        firms_to_run = PROP_FIRMS if run_all else [selected_firm]
        sim_results: list[SimResult] = []

        with st.spinner(f"Running simulator across {len(firms_to_run)} firm(s)..."):
            for firm in firms_to_run:
                try:
                    sim = PropFirmSimulator(
                        firm_name          = firm,
                        account_size       = account_size,
                        strategies         = selected_strategies,
                        symbols            = selected_instruments,
                        timeframe          = tf,
                        risk_per_trade_pct = risk_pct,
                    )
                    res = sim.run(str(start_date), str(end_date))
                    sim_results.append(res)
                except Exception as e:
                    st.warning(f"{firm}: {e}")

        st.session_state["sim_results"] = sim_results

    sim_results: list = st.session_state.get("sim_results", [])

    if sim_results:
        # Firm comparison cards
        st.markdown("### Results by Firm")
        card_cols = st.columns(min(len(sim_results), 3))
        for idx, res in enumerate(sim_results):
            col = card_cols[idx % 3]
            with col:
                stage_color = (
                    "stage-funded" if res.stage_reached == "FUNDED" else
                    "stage-failed" if res.stage_reached == "FAILED" else
                    "stage-active"
                )
                pnl_col = "green" if res.net_pnl_usd >= 0 else "red"
                st.markdown(
                    f"**{res.firm_name}**  "
                    f'<span class="stage-badge {stage_color}">{res.stage_reached}</span>',
                    unsafe_allow_html=True,
                )
                st.metric("Balance", f"${res.final_balance:,.0f}",
                          f"{res.net_pnl_pct:+.2f}%")
                st.metric("Win Rate", f"{res.win_rate:.1f}%")
                st.metric("Max DD", f"{res.max_dd_pct:.2f}%")
                if res.failed_reason:
                    st.caption(f"❌ {res.failed_reason}")
                st.markdown("---")

        # Summary comparison table
        st.markdown("### Firm Comparison")
        rows = []
        for r in sim_results:
            rows.append({
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
        df_cmp = pd.DataFrame(rows)
        st.dataframe(
            df_cmp.style
                .applymap(_pnl_color, subset=["Net P&L $", "Net P&L %"])
                .format({"Final Balance": "${:,.0f}", "Net P&L $": "${:+,.0f}",
                         "Net P&L %": "{:+.2f}%", "Win Rate %": "{:.1f}%",
                         "Max DD %": "{:.2f}%", "Profit Factor": "{:.2f}"}),
            use_container_width=True,
        )

        # Stage progression
        st.markdown("### Stage Progression")
        sel_firm_label = st.selectbox("Firm detail", [r.firm_name for r in sim_results],
                                      key="sim_firm_sel")
        sel_sim = next(r for r in sim_results if r.firm_name == sel_firm_label)

        if sel_sim.stage_history:
            sh_df = pd.DataFrame(sel_sim.stage_history)
            st.dataframe(sh_df, use_container_width=True)
        else:
            st.info("No stage transitions recorded yet.")

        # Equity curve from sim trades
        closed_sim = [t for t in sel_sim.trades if t.result in ("WIN", "LOSS", "BE")]
        if closed_sim:
            balance_curve = []
            bal = account_size
            for t in closed_sim:
                bal += t.pnl_usd
                balance_curve.append({"trade": t.trade_id, "balance": bal,
                                      "result": t.result, "stage": t.stage})
            df_curve = pd.DataFrame(balance_curve)
            colors = ["#00d4aa" if r == "WIN" else "#ff4b4b" for r in df_curve["result"]]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_curve["trade"], y=df_curve["balance"],
                mode="lines+markers",
                line=dict(color="#00d4aa", width=2),
                fill="tozeroy", fillcolor="rgba(0,212,170,0.08)",
                marker=dict(color=colors, size=5),
                name="Balance",
            ))
            fig.add_hline(y=account_size, line_dash="dash", line_color="gray",
                          annotation_text="Start")
            fig.update_layout(
                title=f"{sel_firm_label} — Equity Curve",
                template="plotly_dark", height=350,
                xaxis_title="Trade #", yaxis_title="Balance ($)",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Trade log
        st.markdown("### Trade Log")
        if sel_sim.trades:
            df_log = pd.DataFrame([
                {
                    "#":       t.trade_id,
                    "Strategy": t.strategy,
                    "Symbol":   t.symbol,
                    "Dir":      t.direction,
                    "Entry":    t.entry_price,
                    "SL":       t.sl_price,
                    "TP":       t.tp_price,
                    "R:R":      round(t.risk_rr, 2),
                    "Lot":      t.lot_size,
                    "Result":   t.result,
                    "P&L $":    t.pnl_usd,
                    "Stage":    t.stage,
                    "DD%":      t.daily_dd_pct,
                    "Blocked":  t.block_reason or "",
                }
                for t in sel_sim.trades
            ])
            st.dataframe(
                df_log.style
                    .applymap(_color_result, subset=["Result"])
                    .applymap(_pnl_color, subset=["P&L $"]),
                use_container_width=True,
                height=400,
            )

    elif not (run_single or run_all):
        st.info("Configure sidebar and click **Simulate** to run the prop firm challenge.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_live:
    st.markdown("## Live Trading Dashboard")

    # Try to connect to the FastAPI backend
    live_col1, live_col2, live_col3 = st.columns([2, 1, 1])
    with live_col1:
        api_url = st.text_input("API URL", value="http://localhost:8000", key="api_url")
    with live_col2:
        refresh = st.button("🔄 Refresh", key="live_refresh")
    with live_col3:
        auto_refresh = st.checkbox("Auto-refresh (30s)", key="auto_refresh")

    if auto_refresh:
        import time
        time.sleep(0.1)
        st.rerun()

    dashboard_data = None
    trades_data    = None
    agents_data    = None
    error_msg      = None

    if refresh or auto_refresh or True:
        try:
            import requests
            resp = requests.get(f"{api_url}/dashboard", timeout=3)
            if resp.ok:
                dashboard_data = resp.json()
            resp2 = requests.get(f"{api_url}/trades/today", timeout=3)
            if resp2.ok:
                trades_data = resp2.json()
            resp3 = requests.get(f"{api_url}/agents/status", timeout=3)
            if resp3.ok:
                agents_data = resp3.json()
        except Exception as e:
            error_msg = str(e)

    if error_msg:
        st.warning(f"Cannot reach API at `{api_url}` — showing demo data. ({error_msg})")
        # Fallback demo data
        dashboard_data = {
            "balance": 100_420.50,
            "equity": 100_420.50,
            "daily_pnl": 420.50,
            "daily_dd_pct": 0.18,
            "total_dd_pct": 0.21,
            "open_trades": 0,
            "session": "London",
            "active_firm": "FundingPips",
            "stage": "STAGE1",
            "win_rate_today": 66.7,
            "trades_today": 3,
            "wins_today": 2,
        }
        trades_data = []
        agents_data = {
            "agent_01": "IDLE", "agent_02": "IDLE", "agent_03": "IDLE",
            "agent_04": "IDLE", "agent_05": "IDLE", "agent_06": "IDLE",
            "agent_07": "IDLE", "agent_08": "IDLE",
        }

    if dashboard_data:
        # Account health row
        st.markdown("### Account Health")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            _metric("Balance", f"${dashboard_data.get('balance', 0):,.2f}")
        with m2:
            dpnl = dashboard_data.get("daily_pnl", 0)
            _metric("Daily P&L", f"${dpnl:+,.2f}",
                    "green" if dpnl >= 0 else "red")
        with m3:
            ddd = dashboard_data.get("daily_dd_pct", 0)
            _metric("Daily DD %", f"{ddd:.3f}%",
                    "green" if ddd < 2 else "orange" if ddd < 4 else "red")
        with m4:
            tdd = dashboard_data.get("total_dd_pct", 0)
            _metric("Total DD %", f"{tdd:.3f}%",
                    "green" if tdd < 4 else "orange" if tdd < 7 else "red")
        with m5:
            _metric("Open Trades", str(dashboard_data.get("open_trades", 0)))
        with m6:
            wr = dashboard_data.get("win_rate_today", 0)
            _metric("Win Rate Today", f"{wr:.1f}%",
                    "green" if wr >= 60 else "orange" if wr >= 50 else "red")

        st.markdown("---")

        # Session + firm info
        info_col, agent_col = st.columns([1, 1])
        with info_col:
            st.markdown("### Session Info")
            st.markdown(f"**Firm:** {dashboard_data.get('active_firm', '—')}  "
                        f"**Stage:** {dashboard_data.get('stage', '—')}  "
                        f"**Session:** {dashboard_data.get('session', '—')}")
            st.markdown(f"**Trades today:** {dashboard_data.get('trades_today', 0)} "
                        f"({dashboard_data.get('wins_today', 0)} wins)")

        with agent_col:
            st.markdown("### Agent Status")
            if agents_data:
                agent_names = {
                    "agent_01": "News Sentinel",
                    "agent_02": "Signal Hunter",
                    "agent_03": "Strategy Oracle",
                    "agent_04": "Risk Enforcer",
                    "agent_05": "Executor",
                    "agent_06": "Recorder",
                    "agent_07": "Forecaster",
                    "agent_08": "Orchestrator",
                }
                cols = st.columns(4)
                for i, (aid, aname) in enumerate(agent_names.items()):
                    status = agents_data.get(aid, "IDLE")
                    icon = "🟢" if status == "RUNNING" else "⚪"
                    cols[i % 4].markdown(f"{icon} **{aid}**  \n{aname}")

        st.markdown("---")

        # Today's trades table
        st.markdown("### Today's Trades")
        if trades_data:
            df_live = pd.DataFrame(trades_data)
            st.dataframe(df_live, use_container_width=True, height=300)
        else:
            st.info("No trades recorded today.")

        # Bot controls
        st.markdown("### Bot Controls")
        ctrl1, ctrl2, ctrl3 = st.columns(3)
        with ctrl1:
            if st.button("▶ Start Bot", type="primary"):
                try:
                    import requests
                    r = requests.post(f"{api_url}/agents/start", timeout=5)
                    st.success("Bot started." if r.ok else f"Error: {r.text}")
                except Exception as e:
                    st.error(f"Cannot reach API: {e}")
        with ctrl2:
            if st.button("⏹ Stop Bot"):
                try:
                    import requests
                    r = requests.post(f"{api_url}/agents/stop", timeout=5)
                    st.success("Bot stopped." if r.ok else f"Error: {r.text}")
                except Exception as e:
                    st.error(f"Cannot reach API: {e}")
        with ctrl3:
            mode = st.selectbox("Trade Mode", ["PAPER (Virtual)", "LIVE (Real)"],
                                key="trade_mode")
            if "LIVE" in mode:
                st.warning("Live mode sends real orders. Use with caution.")

    else:
        st.info("Click **Refresh** or start the ForgeX API server to see live data.")
        st.code("# Start the API server:\npython app.py", language="bash")
