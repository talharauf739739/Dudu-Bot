"""
Virtual Account — paper trading account that tracks balance,
drawdown, P&L, and daily resets exactly like a real prop firm account.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class DailyRecord:
    date: str
    start_balance: float
    end_balance: float
    trades: int
    wins: int
    losses: int
    pnl_usd: float
    daily_dd_pct: float
    blocked_trades: int


@dataclass
class VirtualTrade:
    trade_id:    int
    symbol:      str
    strategy:    str
    direction:   str
    entry_price: float
    sl_price:    float
    tp_price:    float
    lot_size:    float
    risk_rr:     float
    open_time:   datetime
    close_time:  Optional[datetime] = None
    exit_price:  float = 0.0
    result:      str = "OPEN"          # OPEN | WIN | LOSS | BE | BLOCKED
    pnl_usd:     float = 0.0
    hold_sec:    int = 0
    block_reason: str = ""


class VirtualAccount:
    """
    Simulates a live trading account with full prop firm metrics.
    Used by the Prop Firm Simulator for paper trading.
    """

    def __init__(self, account_size: float, firm_name: str, account_id: str = "DEMO"):
        self.firm_name       = firm_name
        self.account_id      = account_id
        self.initial_balance = account_size
        self.balance         = account_size
        self.equity          = account_size
        self.peak_balance    = account_size

        self._trades: list[VirtualTrade] = []
        self._daily_records: list[DailyRecord] = []
        self._current_day: Optional[str] = None
        self._day_start_balance: float = account_size
        self._trade_counter: int = 0

    # ── Balance metrics ────────────────────────────────────────────────────────

    @property
    def daily_pnl(self) -> float:
        return round(self.balance - self._day_start_balance, 2)

    @property
    def daily_dd_pct(self) -> float:
        loss = self._day_start_balance - self.balance
        return round(loss / self.initial_balance * 100, 3) if loss > 0 else 0.0

    @property
    def total_dd_pct(self) -> float:
        loss = self.peak_balance - self.balance
        return round(loss / self.initial_balance * 100, 3) if loss > 0 else 0.0

    @property
    def total_profit_pct(self) -> float:
        return round((self.balance - self.initial_balance) / self.initial_balance * 100, 3)

    # ── Trade management ───────────────────────────────────────────────────────

    def _check_new_day(self):
        today = date.today().isoformat()
        if self._current_day != today:
            if self._current_day is not None:
                self._save_daily_record()
            self._current_day = today
            self._day_start_balance = self.balance

    def open_trade(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        lot_size: float,
        risk_rr: float = 2.0,
    ) -> VirtualTrade:
        self._check_new_day()
        self._trade_counter += 1
        trade = VirtualTrade(
            trade_id    = self._trade_counter,
            symbol      = symbol,
            strategy    = strategy,
            direction   = direction,
            entry_price = entry_price,
            sl_price    = sl_price,
            tp_price    = tp_price,
            lot_size    = lot_size,
            risk_rr     = risk_rr,
            open_time   = datetime.utcnow(),
        )
        self._trades.append(trade)
        return trade

    def close_trade(
        self,
        trade: VirtualTrade,
        exit_price: float,
        result: str,
        pnl_usd: float,
        hold_sec: int = 0,
    ):
        trade.exit_price = exit_price
        trade.result     = result
        trade.pnl_usd    = pnl_usd
        trade.hold_sec   = hold_sec
        trade.close_time = datetime.utcnow()

        self.balance += pnl_usd
        self.equity   = self.balance
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance

    def block_trade(self, trade: VirtualTrade, reason: str):
        trade.result       = "BLOCKED"
        trade.block_reason = reason
        trade.close_time   = datetime.utcnow()

    def _save_daily_record(self):
        day_trades = [t for t in self._trades
                      if t.open_time.date().isoformat() == self._current_day
                      and t.result != "OPEN"]
        self._daily_records.append(DailyRecord(
            date           = self._current_day,
            start_balance  = self._day_start_balance,
            end_balance    = self.balance,
            trades         = len(day_trades),
            wins           = sum(1 for t in day_trades if t.result == "WIN"),
            losses         = sum(1 for t in day_trades if t.result == "LOSS"),
            pnl_usd        = sum(t.pnl_usd for t in day_trades),
            daily_dd_pct   = self.daily_dd_pct,
            blocked_trades = sum(1 for t in day_trades if t.result == "BLOCKED"),
        ))

    # ── Reporting ──────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        closed = [t for t in self._trades if t.result in ("WIN", "LOSS", "BE")]
        wins   = sum(1 for t in closed if t.result == "WIN")
        return {
            "account_id":     self.account_id,
            "firm":           self.firm_name,
            "initial":        self.initial_balance,
            "balance":        round(self.balance, 2),
            "total_profit_pct": self.total_profit_pct,
            "total_dd_pct":   self.total_dd_pct,
            "daily_dd_pct":   self.daily_dd_pct,
            "total_trades":   len(closed),
            "wins":           wins,
            "losses":         len(closed) - wins,
            "win_rate":       round(wins / len(closed) * 100, 1) if closed else 0.0,
            "net_pnl":        round(self.balance - self.initial_balance, 2),
        }

    @property
    def trades(self) -> list[VirtualTrade]:
        return self._trades

    @property
    def daily_records(self) -> list[DailyRecord]:
        return self._daily_records
