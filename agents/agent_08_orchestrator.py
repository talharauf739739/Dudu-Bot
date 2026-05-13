"""
Agent-08 — Orchestrator (Master Controller)
LangGraph StateGraph that routes all agents.
Session timer, circuit breaker, final approval gate.
Routes: 01 → 02 → 03 → 04 → 05 → 06
Agent-07 runs at end-of-session.
"""

import pytz
from datetime import datetime
from langgraph.graph import StateGraph, START, END

from core.state import ForgeXState, initial_state
from core.config import settings
from core.mcp_client import telegram_mcp, tradelocker

import agents.agent_01_news_sentinel as agent01
import agents.agent_02_signal_hunter as agent02
import agents.agent_03_strategy_oracle as agent03
import agents.agent_04_risk_enforcer as agent04
import agents.agent_05_executor as agent05
import agents.agent_06_recorder as agent06
import agents.agent_07_forecaster as agent07
from agents.agent_06_recorder import send_end_of_session_summary

GMT = pytz.timezone("UTC")

CIRCUIT_BREAKER_THRESHOLD = 0.80   # 80% of daily DD limit triggers pause


def _parse_time(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def _get_current_session() -> str:
    now = datetime.now(GMT)
    h, m = now.hour, now.minute
    current = h * 60 + m

    lon_start = sum(_parse_time(settings.SESSION_LONDON_START)[i] * [60, 1][i] for i in range(2))
    lon_end   = sum(_parse_time(settings.SESSION_LONDON_END)[i] * [60, 1][i] for i in range(2))
    ny_start  = sum(_parse_time(settings.SESSION_NY_START)[i] * [60, 1][i] for i in range(2))
    ny_end    = sum(_parse_time(settings.SESSION_NY_END)[i] * [60, 1][i] for i in range(2))

    if lon_start <= current < lon_end:
        return "LONDON"
    if ny_start <= current < ny_end:
        return "NY"
    return "SLEEP"


def _check_circuit_breaker(state: ForgeXState) -> bool:
    """Trigger circuit breaker at 80% of daily DD limit."""
    from core.mcp_client import propfirm_mcp
    rules = propfirm_mcp.call("get_firm_rules", firm_name=state.get("prop_firm", "FundedNext"))
    daily_limit = rules.get("daily_dd_pct", 5.0)
    consumed = state.get("daily_dd_pct", 0.0)
    return consumed >= (daily_limit * CIRCUIT_BREAKER_THRESHOLD)


# ── LangGraph Node Wrappers ────────────────────────────────────────────────────

def session_check(state: ForgeXState) -> ForgeXState:
    session = _get_current_session()
    active = session in ("LONDON", "NY")
    logs = list(state.get("agent_logs", []))
    logs.append(f"[Agent-08] Session: {session} | Active: {active}")
    return {**state, "current_session": session, "session_active": active, "agent_logs": logs}


def news_check(state: ForgeXState) -> ForgeXState:
    return agent01.run(state)


def signal_scan(state: ForgeXState) -> ForgeXState:
    return agent02.run(state)


def strategy_pick(state: ForgeXState) -> ForgeXState:
    return agent03.run(state)


def risk_check(state: ForgeXState) -> ForgeXState:
    return agent04.run(state)


def execute_trade(state: ForgeXState) -> ForgeXState:
    return agent05.run(state)


def record_trade(state: ForgeXState) -> ForgeXState:
    return agent06.run(state)


def end_of_session(state: ForgeXState) -> ForgeXState:
    logs = list(state.get("agent_logs", []))
    logs.append("[Agent-08] Session ending — running Forecaster and summary")
    state = {**state, "agent_logs": logs}
    state = agent07.run(state)
    send_end_of_session_summary(state)
    return state


# ── Conditional Routing ────────────────────────────────────────────────────────

def route_after_session(state: ForgeXState) -> str:
    if not state.get("session_active"):
        return "sleep"
    if state.get("circuit_breaker"):
        return "sleep"
    if _check_circuit_breaker(state):
        telegram_mcp.call("send_circuit_breaker",
                          reason=f"Daily DD at {state.get('daily_dd_pct', 0):.2f}% (80% threshold hit)")
        return "sleep"
    return "news_check"


def route_after_signal(state: ForgeXState) -> str:
    return "strategy_pick" if state.get("selected_setup") else "record_trade"


def route_after_strategy(state: ForgeXState) -> str:
    return "risk_check" if state.get("selected_trade") else "record_trade"


def route_after_risk(state: ForgeXState) -> str:
    return "execute_trade" if state.get("risk_verdict") == "APPROVED" else "record_trade"


# ── Build Graph ────────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(ForgeXState)

    g.add_node("session_check",  session_check)
    g.add_node("news_check",     news_check)
    g.add_node("signal_scan",    signal_scan)
    g.add_node("strategy_pick",  strategy_pick)
    g.add_node("risk_check",     risk_check)
    g.add_node("execute_trade",  execute_trade)
    g.add_node("record_trade",   record_trade)
    g.add_node("end_of_session", end_of_session)

    g.add_edge(START, "session_check")

    g.add_conditional_edges("session_check", route_after_session, {
        "news_check": "news_check",
        "sleep": END,
    })

    g.add_edge("news_check", "signal_scan")

    g.add_conditional_edges("signal_scan", route_after_signal, {
        "strategy_pick": "strategy_pick",
        "record_trade":  "record_trade",
    })

    g.add_conditional_edges("strategy_pick", route_after_strategy, {
        "risk_check":   "risk_check",
        "record_trade": "record_trade",
    })

    g.add_conditional_edges("risk_check", route_after_risk, {
        "execute_trade": "execute_trade",
        "record_trade":  "record_trade",
    })

    g.add_edge("execute_trade", "record_trade")
    g.add_edge("record_trade",  END)

    return g.compile()


# ── Main entry point ──────────────────────────────────────────────────────────

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_cycle(state: ForgeXState) -> ForgeXState:
    """Run one full agent cycle (one signal opportunity)."""
    graph = get_graph()
    result = graph.invoke(state)
    return result


def start_session(prop_firm: str = None, account_id: str = None) -> ForgeXState:
    """Initialize state and run session loop until market closes."""
    firm = prop_firm or settings.ACTIVE_PROP_FIRM
    acc  = account_id or settings.ACTIVE_ACCOUNT_ID

    state = initial_state(firm, acc)
    print(f"[Agent-08] ForgeX AI starting — Firm: {firm} | Account: {acc}")

    while True:
        session = _get_current_session()
        if session == "SLEEP":
            print("[Agent-08] Outside session hours — system sleeping")
            break

        state = run_cycle(state)

        # Reset per-trade fields for next cycle
        state = {
            **state,
            "selected_setup": None,
            "selected_trade": None,
            "risk_verdict": "PENDING",
            "risk_block_reason": None,
            "order_result": None,
            "trade_closed": False,
            "close_price": None,
            "pnl_usd": None,
            "hold_time_s": None,
            "iteration": state.get("iteration", 0) + 1,
        }

    # End of session
    end_of_session(state)
    return state


if __name__ == "__main__":
    start_session()
