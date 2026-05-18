from fastapi import APIRouter
from api.schemas.trade_schema import DashboardOut, SystemStateOut, AgentStatusOut
from core.mcp_client import journal_mcp, broker
from core.config import settings

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

AGENT_NAMES = {
    "agent_01": "News Sentinel",
    "agent_02": "Signal Hunter",
    "agent_03": "Strategy Oracle",
    "agent_04": "Risk Enforcer",
    "agent_05": "Executor",
    "agent_06": "Recorder",
    "agent_07": "Forecaster",
    "agent_08": "Orchestrator",
}

# In-memory state reference (updated by Orchestrator)
_system_state: dict = {}


def update_state(state: dict):
    """Called by Agent-08 to push current state to the API layer."""
    global _system_state
    _system_state = state


@router.get("/", response_model=DashboardOut)
def get_dashboard():
    state = _system_state

    daily_stats = {}
    try:
        daily_stats = journal_mcp.call("get_daily_stats")
    except Exception:
        pass

    balance = state.get("account_balance", 0.0)
    if not balance:
        try:
            balance = broker.call("get_account_balance").get("balance", 0.0)
        except Exception:
            pass

    system = SystemStateOut(
        session_active=state.get("session_active", False),
        current_session=state.get("current_session", "SLEEP"),
        prop_firm=state.get("prop_firm", settings.ACTIVE_PROP_FIRM),
        account_id=state.get("account_id", settings.ACTIVE_ACCOUNT_ID),
        circuit_breaker=state.get("circuit_breaker", False),
        daily_dd_pct=state.get("daily_dd_pct", 0.0),
        total_dd_pct=state.get("total_dd_pct", 0.0),
        account_balance=balance,
        session_wins=state.get("session_wins", 0),
        session_losses=state.get("session_losses", 0),
        iteration=state.get("iteration", 0),
        error=state.get("error"),
    )

    agents = [
        AgentStatusOut(
            agent_id=k,
            name=v,
            status="IDLE",
            last_action="",
            last_run=None,
        )
        for k, v in AGENT_NAMES.items()
    ]

    return DashboardOut(
        system=system,
        agents=agents,
        recent_signals=state.get("active_signals", [])[:5],
        todays_trades=daily_stats.get("total_trades", 0),
        todays_pnl=daily_stats.get("net_pnl", 0.0),
        todays_win_rate=daily_stats.get("win_rate", 0.0),
    )


@router.get("/state/raw")
def get_raw_state():
    """Full LangGraph state dump for debugging."""
    return _system_state
