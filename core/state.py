from typing import TypedDict, Optional, List, Dict, Any


class ForgeXState(TypedDict):
    # ── Session ────────────────────────────────────────────────────────────────
    session_active: bool
    current_session: str             # LONDON | NY | SLEEP

    # ── Agent-01 output ────────────────────────────────────────────────────────
    news_status: Dict[str, Dict]     # currency -> {status, event, time}

    # ── Agent-02 output ────────────────────────────────────────────────────────
    active_signals: List[Dict]       # list of Setup dicts
    selected_setup: Optional[Dict]   # highest scoring setup

    # ── Agent-03 output ────────────────────────────────────────────────────────
    selected_trade: Optional[Dict]   # TradeCandidate dict

    # ── Agent-04 output ────────────────────────────────────────────────────────
    risk_verdict: str                # APPROVED | BLOCKED | PENDING
    risk_block_reason: Optional[str]
    risk_checks_passed: List[str]
    risk_checks_failed: List[str]

    # ── Agent-05 output ────────────────────────────────────────────────────────
    order_result: Optional[Dict]     # OrderResult dict
    active_order_id: Optional[str]
    trade_closed: bool
    close_price: Optional[float]
    pnl_usd: Optional[float]
    hold_time_s: Optional[int]

    # ── Account state ──────────────────────────────────────────────────────────
    account_balance: float
    daily_dd_pct: float
    total_dd_pct: float
    prop_firm: str
    account_id: str

    # ── Circuit breaker ────────────────────────────────────────────────────────
    circuit_breaker: bool            # True = system paused for session
    circuit_reason: Optional[str]

    # ── Session tracking ───────────────────────────────────────────────────────
    session_trades: List[Dict]       # all trades this session
    session_wins: int
    session_losses: int

    # ── Agent-06 output ────────────────────────────────────────────────────────
    trade_id_logged: Optional[int]
    journal_synced: bool
    telegram_sent: bool

    # ── Diagnostics ────────────────────────────────────────────────────────────
    agent_logs: List[str]
    error: Optional[str]
    iteration: int                   # how many signals processed this session


def initial_state(prop_firm: str, account_id: str) -> ForgeXState:
    return ForgeXState(
        session_active=False,
        current_session="SLEEP",
        news_status={},
        active_signals=[],
        selected_setup=None,
        selected_trade=None,
        risk_verdict="PENDING",
        risk_block_reason=None,
        risk_checks_passed=[],
        risk_checks_failed=[],
        order_result=None,
        active_order_id=None,
        trade_closed=False,
        close_price=None,
        pnl_usd=None,
        hold_time_s=None,
        account_balance=0.0,
        daily_dd_pct=0.0,
        total_dd_pct=0.0,
        prop_firm=prop_firm,
        account_id=account_id,
        circuit_breaker=False,
        circuit_reason=None,
        session_trades=[],
        session_wins=0,
        session_losses=0,
        trade_id_logged=None,
        journal_synced=False,
        telegram_sent=False,
        agent_logs=[],
        error=None,
        iteration=0,
    )
