from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────────

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class TradeResult(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BE = "BE"          # breakeven
    BLOCKED = "BLOCKED"
    OPEN = "OPEN"

class NewsSignal(str, Enum):
    SAFE = "NEWS_SAFE"
    BLOCK = "NEWS_BLOCK"

class RiskVerdict(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"

class Session(str, Enum):
    LONDON = "LONDON"
    NY = "NY"
    SLEEP = "SLEEP"

class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# ── News & Calendar ────────────────────────────────────────────────────────────

class NewsEvent(BaseModel):
    time: str
    currency: str
    impact: str          # HIGH | MEDIUM | LOW
    name: str
    forecast: Optional[str] = None
    previous: Optional[str] = None

class NewsStatus(BaseModel):
    currency: str
    status: NewsSignal
    event: Optional[str] = None
    event_time: Optional[str] = None
    resume_time: Optional[str] = None


# ── Market Signals ─────────────────────────────────────────────────────────────

class Setup(BaseModel):
    symbol: str
    timeframe: str                   # 1min | 5min
    pattern: str                     # ORDER_BLOCK+FVG | BOS+CHOCH | EMA_CROSS ...
    score: float = Field(ge=1, le=10)
    entry_zone: float
    session: str
    direction: Optional[Direction] = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)


# ── Strategy ───────────────────────────────────────────────────────────────────

class Strategy(BaseModel):
    id: str                          # S-01 … S-10
    name: str
    instruments: List[str]
    timeframes: List[str]
    patterns: List[str]
    sessions: List[str]
    win_rate_min: float
    win_rate_max: float
    rr_min: float
    rr_max: float
    bot_ok: bool
    entry_rule: str = ""
    sl_rule: str = ""
    tp_rule: str = ""


# ── Trade ──────────────────────────────────────────────────────────────────────

class TradeCandidate(BaseModel):
    symbol: str
    direction: Direction
    entry_price: float
    sl_price: float
    tp_price: float
    strategy_id: str
    risk_rr: float
    timeframe: str
    session: str
    lot_size: float = 0.0            # calculated by Agent-04
    expected_win_rate: float = 0.0

class TradeRecord(BaseModel):
    trade_id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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
    result: Optional[str] = None
    close_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    hold_time_s: Optional[int] = None
    prop_firm: str
    account_id: str
    daily_dd_pct: Optional[float] = None
    notes: Optional[str] = None


# ── Order / Position ───────────────────────────────────────────────────────────

class OrderResult(BaseModel):
    order_id: str
    symbol: str
    direction: str
    filled_price: float
    lot_size: float
    sl: float
    tp: float
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class Position(BaseModel):
    order_id: str
    symbol: str
    direction: str
    entry_price: float
    current_price: float
    sl: float
    tp: float
    lot_size: float
    unrealized_pnl: float
    hold_time_s: int

class BalanceSummary(BaseModel):
    account_id: str
    balance: float
    equity: float
    used_margin: float
    free_margin: float
    daily_pnl: float
    daily_dd_pct: float


# ── Prop Firm Rules ────────────────────────────────────────────────────────────

class FirmRules(BaseModel):
    firm_name: str
    p1_target_pct: float
    p2_target_pct: float
    daily_dd_pct: float
    max_dd_pct: float
    payout_pct: float
    ea_bots: str                     # FULL | PARTIAL | NO
    min_hold_sec: int
    scalping_allowed: bool
    news_trading_allowed: bool
    consistency_rule: bool
    max_single_day_pct: float        # consistency cap (e.g. 35%)
    weekend_hold: bool

class RiskCheckResult(BaseModel):
    verdict: RiskVerdict
    reason: Optional[str] = None
    checks_passed: List[str] = Field(default_factory=list)
    checks_failed: List[str] = Field(default_factory=list)


# ── Journal / Analytics ────────────────────────────────────────────────────────

class StrategyStats(BaseModel):
    strategy_id: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_rr: float
    avg_pnl: float
    best_session: str
    best_instrument: str

class DailySummary(BaseModel):
    date: str
    session: str
    duration_min: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_rr: float
    net_pnl: float
    best_strategy: str
    prop_firm_dd: Dict[str, float]   # firm -> daily_dd_pct
    tomorrow_forecast: Optional[str] = None


# ── Agent System ───────────────────────────────────────────────────────────────

class AgentLog(BaseModel):
    agent: str
    level: str = "INFO"              # INFO | WARN | ERROR
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
