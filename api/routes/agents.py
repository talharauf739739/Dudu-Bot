from fastapi import APIRouter, HTTPException
from core.config import settings
from core.state import initial_state

router = APIRouter(prefix="/agents", tags=["Agents"])

_orchestrator_task = None


@router.get("/status")
def agents_status():
    from api.routes.dashboard import _system_state
    logs = _system_state.get("agent_logs", [])[-20:]  # last 20 log lines
    return {
        "session_active": _system_state.get("session_active", False),
        "current_session": _system_state.get("current_session", "SLEEP"),
        "circuit_breaker": _system_state.get("circuit_breaker", False),
        "recent_logs": logs,
        "iteration": _system_state.get("iteration", 0),
    }


@router.get("/logs")
def get_logs(limit: int = 50):
    from api.routes.dashboard import _system_state
    logs = _system_state.get("agent_logs", [])
    return {"logs": logs[-limit:]}


@router.post("/start")
def start_orchestrator(prop_firm: str = None, account_id: str = None):
    """
    Start the Orchestrator in a background thread.
    In production, use a process manager (supervisord / systemd) instead.
    """
    import threading
    from agents.agent_08_orchestrator import start_session

    firm = prop_firm or settings.ACTIVE_PROP_FIRM
    acc  = account_id or settings.ACTIVE_ACCOUNT_ID

    def _run():
        start_session(prop_firm=firm, account_id=acc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "prop_firm": firm, "account_id": acc}


@router.post("/stop")
def stop_orchestrator():
    """
    Signal the orchestrator to stop after current cycle.
    Sets circuit breaker to end gracefully.
    """
    from api.routes.dashboard import _system_state, update_state
    update_state({**_system_state, "circuit_breaker": True, "circuit_reason": "Manual stop via API"})
    return {"status": "stop_requested"}
