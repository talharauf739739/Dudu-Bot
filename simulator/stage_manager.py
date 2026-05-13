"""
Stage Manager — tracks prop firm challenge progression.
Stage 1 → Stage 2 → Funded based on profit targets and rule compliance.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


RULES_PATH = Path(__file__).parent.parent / "knowledge_base" / "prop_firms" / "rules.json"


@dataclass
class StageResult:
    stage:        str
    passed:       bool
    reason:       str
    profit_pct:   float
    max_dd_pct:   float
    trading_days: int


@dataclass
class StageState:
    firm_name:        str
    current_stage:    str          # STAGE1 | STAGE2 | FUNDED | FAILED
    balance:          float
    initial_balance:  float
    peak_balance:     float
    trading_days:     int
    stage_history:    list[StageResult] = field(default_factory=list)
    failed_reason:    str = ""

    @property
    def profit_pct(self) -> float:
        return round((self.balance - self.initial_balance) / self.initial_balance * 100, 3)

    @property
    def total_dd_pct(self) -> float:
        loss = self.peak_balance - self.balance
        return round(loss / self.initial_balance * 100, 3) if loss > 0 else 0.0

    @property
    def is_active(self) -> bool:
        return self.current_stage not in ("FAILED", "FUNDED")


def _load_firm_rules(firm_name: str) -> dict:
    with open(RULES_PATH) as f:
        data = json.load(f)
    firms = {f["firm_name"].lower(): f for f in data["prop_firms"]}
    key = firm_name.lower()
    if key not in firms:
        # fuzzy fallback
        for k, v in firms.items():
            if key in k or k in key:
                return v
        raise ValueError(f"Firm '{firm_name}' not found in rules.json. Available: {list(firms.keys())}")
    return firms[key]


class StageManager:
    """
    Manages prop firm challenge progression for a single account.

    Stage rules are loaded from knowledge_base/prop_firms/rules.json.
    Checks profit targets, DD limits, and minimum trading days.
    """

    STAGE_ORDER = ["STAGE1", "STAGE2", "FUNDED"]

    def __init__(self, firm_name: str, account_size: float):
        self.firm_rules   = _load_firm_rules(firm_name)
        self.account_size = account_size
        self.state        = StageState(
            firm_name     = self.firm_rules["firm_name"],
            current_stage = "STAGE1",
            balance       = account_size,
            initial_balance = account_size,
            peak_balance  = account_size,
            trading_days  = 0,
        )

    # ── Stage rule lookup ───────────────────────────────────────────────────────

    def _stage_rules(self, stage: str) -> dict:
        """Extract rules for a given stage from the firm rules dict."""
        rules = self.firm_rules
        stage_lower = stage.lower()

        # Direct stage keys in rules.json vary by firm; normalise here
        if stage_lower == "stage1":
            return {
                "profit_target_pct": rules.get("phase1_profit_target_pct",
                                               rules.get("profit_target_pct", 8.0)),
                "daily_dd_pct":      rules.get("daily_dd_pct", 5.0),
                "max_dd_pct":        rules.get("max_dd_pct",
                                               rules.get("phase1_max_dd_pct", 10.0)),
                "min_trading_days":  rules.get("min_trading_days", 5),
            }
        elif stage_lower == "stage2":
            return {
                "profit_target_pct": rules.get("phase2_profit_target_pct",
                                               rules.get("profit_target_pct", 5.0)),
                "daily_dd_pct":      rules.get("daily_dd_pct", 5.0),
                "max_dd_pct":        rules.get("max_dd_pct",
                                               rules.get("phase2_max_dd_pct", 10.0)),
                "min_trading_days":  rules.get("min_trading_days", 5),
            }
        else:  # FUNDED
            return {
                "profit_target_pct": rules.get("funded_profit_target_pct", 0.0),
                "daily_dd_pct":      rules.get("daily_dd_pct", 5.0),
                "max_dd_pct":        rules.get("max_dd_pct",
                                               rules.get("funded_max_dd_pct", 8.0)),
                "min_trading_days":  0,
            }

    # ── Balance updates ─────────────────────────────────────────────────────────

    def update_balance(self, new_balance: float, trading_day_elapsed: bool = False):
        """Called after each trade or at end of day."""
        self.state.balance = new_balance
        if new_balance > self.state.peak_balance:
            self.state.peak_balance = new_balance
        if trading_day_elapsed:
            self.state.trading_days += 1

    # ── Rule checks ─────────────────────────────────────────────────────────────

    def check_dd_violated(self, daily_dd_pct: float = 0.0) -> tuple[bool, str]:
        """Returns (violated, reason). Call after every trade."""
        rules = self._stage_rules(self.state.current_stage)
        if self.state.total_dd_pct >= rules["max_dd_pct"]:
            return True, (f"Total DD {self.state.total_dd_pct:.2f}% "
                          f">= limit {rules['max_dd_pct']}%")
        if daily_dd_pct >= rules["daily_dd_pct"]:
            return True, (f"Daily DD {daily_dd_pct:.2f}% "
                          f">= limit {rules['daily_dd_pct']}%")
        return False, ""

    def fail_account(self, reason: str):
        self.state.current_stage = "FAILED"
        self.state.failed_reason = reason

    # ── Stage progression ───────────────────────────────────────────────────────

    def try_advance_stage(self) -> Optional[StageResult]:
        """
        Check if the current stage objective is met.
        If yes, advance to next stage and return a StageResult.
        Returns None if not yet eligible.
        """
        if not self.state.is_active:
            return None

        stage = self.state.current_stage
        rules = self._stage_rules(stage)

        profit_ok  = self.state.profit_pct >= rules["profit_target_pct"]
        days_ok    = self.state.trading_days >= rules["min_trading_days"]
        dd_ok      = self.state.total_dd_pct < rules["max_dd_pct"]

        if profit_ok and days_ok and dd_ok:
            result = StageResult(
                stage        = stage,
                passed       = True,
                reason       = (f"Profit {self.state.profit_pct:.2f}% >= "
                                f"{rules['profit_target_pct']}% target in "
                                f"{self.state.trading_days} days"),
                profit_pct   = self.state.profit_pct,
                max_dd_pct   = self.state.total_dd_pct,
                trading_days = self.state.trading_days,
            )
            self.state.stage_history.append(result)
            self._advance()
            return result

        return None

    def _advance(self):
        idx = self.STAGE_ORDER.index(self.state.current_stage)
        if idx < len(self.STAGE_ORDER) - 1:
            next_stage = self.STAGE_ORDER[idx + 1]
            # Reset balance tracking for new stage (balance carries over)
            self.state.initial_balance = self.state.balance
            self.state.peak_balance    = self.state.balance
            self.state.trading_days    = 0
            self.state.current_stage   = next_stage
        else:
            self.state.current_stage = "FUNDED"

    # ── Summary ─────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        rules = self._stage_rules(self.state.current_stage)
        return {
            "firm":           self.state.firm_name,
            "current_stage":  self.state.current_stage,
            "balance":        round(self.state.balance, 2),
            "profit_pct":     self.state.profit_pct,
            "total_dd_pct":   self.state.total_dd_pct,
            "trading_days":   self.state.trading_days,
            "target_profit":  rules.get("profit_target_pct", 0),
            "max_dd_limit":   rules.get("max_dd_pct", 10),
            "daily_dd_limit": rules.get("daily_dd_pct", 5),
            "stages_passed":  [s.stage for s in self.state.stage_history if s.passed],
            "failed":         self.state.current_stage == "FAILED",
            "failed_reason":  self.state.failed_reason,
        }
