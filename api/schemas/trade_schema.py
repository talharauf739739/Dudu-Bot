from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TradeOut(BaseModel):
    trade_id: int
    timestamp: datetime
    instrument: str
    direction: str
    strategy_id: str
    timeframe: str
    session: str
    entry_price: float
    sl_price: float
    tp_price: float
    risk_rr: float
    lot_size: float
    result: Optional[str]
    close_price: Optional[float]
    pnl_usd: Optional[float]
    hold_time_s: Optional[int]
    prop_firm: str
    account_id: str
    daily_dd_pct: Optional[float]
    notes: Optional[str]

    class Config:
        from_attributes = True


class AgentStatusOut(BaseModel):
    agent_id: str
    name: str
    status: str          # RUNNING | IDLE | ERROR
    last_action: str
    last_run: Optional[str]


class SystemStateOut(BaseModel):
    session_active: bool
    current_session: str
    prop_firm: str
    account_id: str
    circuit_breaker: bool
    daily_dd_pct: float
    total_dd_pct: float
    account_balance: float
    session_wins: int
    session_losses: int
    iteration: int
    error: Optional[str]


class DashboardOut(BaseModel):
    system: SystemStateOut
    agents: List[AgentStatusOut]
    recent_signals: List[dict]
    todays_trades: int
    todays_pnl: float
    todays_win_rate: float


class EquityPoint(BaseModel):
    date: str
    cumulative_pnl: float


class WinRateByStrategy(BaseModel):
    strategy_id: str
    win_rate: float
    total_trades: int
    avg_rr: float
