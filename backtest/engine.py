"""
Backtesting engine.
Takes OHLC data + strategy signals → simulates trades → returns results.
Enforces prop firm rules at every trade.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BacktestTrade:
    trade_id:       int
    strategy:       str
    symbol:         str
    direction:      str
    entry_price:    float
    sl_price:       float
    tp_price:       float
    risk_rr:        float
    lot_size:       float
    entry_time:     pd.Timestamp
    exit_time:      Optional[pd.Timestamp] = None
    exit_price:     float = 0.0
    result:         str = "OPEN"       # WIN | LOSS | BE | BLOCKED
    pnl_pct:        float = 0.0        # % of account
    pnl_usd:        float = 0.0
    hold_bars:      int = 0
    block_reason:   str = ""
    daily_dd_after: float = 0.0
    total_dd_after: float = 0.0


@dataclass
class BacktestResult:
    strategy:       str
    symbol:         str
    timeframe:      str
    prop_firm:      str
    stage:          str
    account_size:   float
    trades:         list[BacktestTrade] = field(default_factory=list)

    @property
    def closed_trades(self):
        return [t for t in self.trades if t.result in ("WIN", "LOSS", "BE")]

    @property
    def total_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.closed_trades if t.result == "WIN")

    @property
    def losses(self) -> int:
        return sum(1 for t in self.closed_trades if t.result == "LOSS")

    @property
    def win_rate(self) -> float:
        if not self.total_trades:
            return 0.0
        return round(self.wins / self.total_trades * 100, 1)

    @property
    def net_pnl_usd(self) -> float:
        return round(sum(t.pnl_usd for t in self.closed_trades), 2)

    @property
    def net_pnl_pct(self) -> float:
        return round(sum(t.pnl_pct for t in self.closed_trades), 2)

    @property
    def avg_rr(self) -> float:
        rrs = [t.risk_rr for t in self.closed_trades if t.risk_rr > 0]
        return round(sum(rrs) / len(rrs), 2) if rrs else 0.0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.closed_trades:
            return 0.0
        return round(max(t.total_dd_after for t in self.closed_trades), 2)

    @property
    def blocked_trades(self) -> int:
        return sum(1 for t in self.trades if t.result == "BLOCKED")

    @property
    def profit_factor(self) -> float:
        gross_win  = sum(t.pnl_usd for t in self.closed_trades if t.pnl_usd > 0)
        gross_loss = abs(sum(t.pnl_usd for t in self.closed_trades if t.pnl_usd < 0))
        return round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")

    def equity_curve(self) -> list[dict]:
        balance = self.account_size
        curve = []
        for t in self.closed_trades:
            balance += t.pnl_usd
            curve.append({"time": str(t.exit_time), "balance": round(balance, 2),
                          "trade_id": t.trade_id, "result": t.result})
        return curve

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "prop_firm": self.prop_firm,
            "stage": self.stage,
            "account_size": self.account_size,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "net_pnl_usd": self.net_pnl_usd,
            "net_pnl_pct": self.net_pnl_pct,
            "avg_rr": self.avg_rr,
            "max_drawdown_pct": self.max_drawdown_pct,
            "blocked_trades": self.blocked_trades,
            "profit_factor": self.profit_factor,
        }


class BacktestEngine:
    """
    Simulates trading a strategy on historical data.
    Enforces prop firm rules at every signal.
    Tracks equity, drawdown, and stage progression.
    """

    def __init__(
        self,
        account_size: float,
        risk_per_trade_pct: float,
        prop_firm_rules: dict,
        stage: str = "STAGE1",
        min_hold_bars: int = 0,
        pip_value: float = 10.0,   # $ per pip per standard lot
    ):
        self.initial_balance    = account_size
        self.balance            = account_size
        self.peak_balance       = account_size
        self.risk_pct           = risk_per_trade_pct / 100
        self.rules              = prop_firm_rules
        self.stage              = stage
        self.min_hold_bars      = min_hold_bars
        self.pip_value          = pip_value

        self._daily_start: dict[str, float] = {}   # date → balance
        self._trade_counter = 0

    # ── Rule checks ────────────────────────────────────────────────────────────

    def _daily_dd(self, date_key: str) -> float:
        start = self._daily_start.get(date_key, self.balance)
        loss = start - self.balance
        return round(loss / self.initial_balance * 100, 3) if loss > 0 else 0.0

    def _total_dd(self) -> float:
        loss = self.peak_balance - self.balance
        return round(loss / self.initial_balance * 100, 3) if loss > 0 else 0.0

    def _check_rules(self, date_key: str, hold_bars: int) -> tuple[bool, str]:
        daily_dd = self._daily_dd(date_key)
        total_dd = self._total_dd()

        if daily_dd >= self.rules.get("daily_dd_pct", 5):
            return False, f"Daily DD {daily_dd:.2f}% >= {self.rules['daily_dd_pct']}%"
        if self.rules.get("max_dd_pct") and total_dd >= self.rules["max_dd_pct"]:
            return False, f"Total DD {total_dd:.2f}% >= {self.rules['max_dd_pct']}%"
        if hold_bars < self.min_hold_bars:
            return False, f"Hold {hold_bars} bars < min {self.min_hold_bars}"
        return True, ""

    # ── Trade simulation ───────────────────────────────────────────────────────

    def _simulate_trade(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
    ) -> tuple[str, float, int, pd.Timestamp]:
        """Simulate forward from entry bar. Returns (result, exit_price, hold_bars, exit_time)."""
        for j in range(entry_idx + 1, min(entry_idx + 200, len(df))):
            bar = df.iloc[j]
            if direction == "BUY":
                if bar["low"] <= sl:
                    return "LOSS", sl, j - entry_idx, df.index[j]
                if bar["high"] >= tp:
                    return "WIN",  tp, j - entry_idx, df.index[j]
            else:
                if bar["high"] >= sl:
                    return "LOSS", sl, j - entry_idx, df.index[j]
                if bar["low"] <= tp:
                    return "WIN",  tp, j - entry_idx, df.index[j]
        # Timeout — use last bar's close
        last = df.iloc[min(entry_idx + 199, len(df) - 1)]
        result = "WIN" if (direction == "BUY" and last["close"] > entry) or \
                          (direction == "SELL" and last["close"] < entry) else "LOSS"
        return result, last["close"], 199, df.index[min(entry_idx + 199, len(df) - 1)]

    # ── Main run ───────────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        signals: pd.DataFrame,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        prop_firm_name: str,
    ) -> BacktestResult:
        result = BacktestResult(
            strategy=strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            prop_firm=prop_firm_name,
            stage=self.stage,
            account_size=self.initial_balance,
        )

        # Reset state
        self.balance      = self.initial_balance
        self.peak_balance = self.initial_balance
        self._daily_start = {}

        # Align signals with OHLC
        common_idx = df.index.intersection(signals.index)
        signals = signals.loc[common_idx]

        for i, (ts, sig) in enumerate(signals.iterrows()):
            if sig["signal"] is None:
                continue

            # Daily tracking reset
            date_key = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
            if date_key not in self._daily_start:
                self._daily_start[date_key] = self.balance

            # Score filter — only take signals >= 6.0
            if sig["score"] < 6.0:
                continue

            self._trade_counter += 1
            direction = sig["signal"]
            entry     = sig["entry"]
            sl        = sig["sl"]
            tp        = sig["tp"]

            # Validate levels
            if entry <= 0 or sl <= 0 or tp <= 0:
                continue
            if direction == "BUY" and not (sl < entry < tp):
                continue
            if direction == "SELL" and not (tp < entry < sl):
                continue

            # Rule check (pre-trade)
            ok, block_reason = self._check_rules(date_key, self.min_hold_bars + 1)
            if not ok:
                result.trades.append(BacktestTrade(
                    trade_id=self._trade_counter, strategy=strategy_id, symbol=symbol,
                    direction=direction, entry_price=entry, sl_price=sl, tp_price=tp,
                    risk_rr=sig.get("risk_rr", 2.0), lot_size=0,
                    entry_time=ts, result="BLOCKED", block_reason=block_reason,
                ))
                continue

            # Lot size based on risk
            sl_distance = abs(entry - sl)
            risk_usd    = self.balance * self.risk_pct
            # Simplified: 1 lot = $10 per pip, pip = 0.0001 for forex
            pip_size    = 0.0001 if entry < 100 else 1.0
            pips        = sl_distance / pip_size
            lot_size    = round(risk_usd / (pips * self.pip_value), 2)
            lot_size    = max(0.01, min(lot_size, 10.0))

            # Find entry bar in df
            df_locs = df.index.get_loc(ts) if ts in df.index else None
            if df_locs is None:
                continue
            entry_idx = df_locs if isinstance(df_locs, int) else df_locs.start

            # Simulate
            trade_result, exit_price, hold_bars, exit_time = self._simulate_trade(
                df, entry_idx, direction, entry, sl, tp
            )

            # Calc P&L
            if direction == "BUY":
                pnl_pips = (exit_price - entry) / pip_size
            else:
                pnl_pips = (entry - exit_price) / pip_size

            pnl_usd = round(pnl_pips * self.pip_value * lot_size, 2)
            pnl_pct = round(pnl_usd / self.initial_balance * 100, 3)

            self.balance += pnl_usd
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance

            rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0

            result.trades.append(BacktestTrade(
                trade_id    = self._trade_counter,
                strategy    = strategy_id,
                symbol      = symbol,
                direction   = direction,
                entry_price = entry,
                sl_price    = sl,
                tp_price    = tp,
                risk_rr     = rr,
                lot_size    = lot_size,
                entry_time  = ts,
                exit_time   = exit_time,
                exit_price  = exit_price,
                result      = trade_result,
                pnl_pct     = pnl_pct,
                pnl_usd     = pnl_usd,
                hold_bars   = hold_bars,
                daily_dd_after = self._daily_dd(date_key),
                total_dd_after = self._total_dd(),
            ))

        return result
