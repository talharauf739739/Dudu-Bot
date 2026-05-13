"""
MCP Server: mcp-propfirm-kb
Prop Firm Rules Database — Agent-04's source of truth.
Run standalone: python mcp_servers/mcp_propfirm_kb/server.py
"""

import json
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-propfirm-kb")

_RULES_PATH = Path(__file__).parent.parent.parent / "knowledge_base" / "prop_firms" / "rules.json"
_rules_cache: Optional[dict] = None


def _load() -> dict:
    global _rules_cache
    if _rules_cache is None:
        with open(_RULES_PATH) as f:
            _rules_cache = json.load(f)
    return _rules_cache


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_firm_rules(firm_name: str) -> dict:
    """Return all rules for a given prop firm."""
    data = _load()
    return data.get(firm_name, {})


@mcp.tool()
def check_drawdown_ok(firm: str, current_dd: float, dd_type: str) -> dict:
    """
    Check whether current drawdown is within firm limit.
    dd_type: 'daily' | 'total'
    Returns {ok: bool, limit: float, remaining_pct: float}
    """
    rules = get_firm_rules(firm)
    if not rules:
        return {"ok": False, "limit": 0, "remaining_pct": 0, "error": "Firm not found"}

    limit = rules["daily_dd_pct"] if dd_type == "daily" else rules["max_dd_pct"]
    if limit is None:
        return {"ok": True, "limit": 999, "remaining_pct": 999}

    ok = current_dd < limit
    return {"ok": ok, "limit": limit, "remaining_pct": round(limit - current_dd, 2)}


@mcp.tool()
def is_trade_allowed(
    firm: str,
    daily_dd: float,
    total_dd: float,
    position_size_pct: float,
    day_profit_pct: float,
    total_profit_pct: float,
    hold_time_sec: int,
    win_rate: float,
    news_blocked: bool,
    session_active: bool,
) -> dict:
    """
    Run all prop firm rule checks. Returns APPROVED or BLOCKED with reason.
    This is the full Agent-04 gate.
    """
    rules = get_firm_rules(firm)
    if not rules:
        return {"verdict": "BLOCKED", "reason": f"Unknown firm: {firm}"}

    checks_failed = []

    if not session_active:
        checks_failed.append("Session not active (London/NY only)")

    if news_blocked:
        checks_failed.append("News window active — trade blocked by Agent-01")

    if daily_dd >= rules["daily_dd_pct"]:
        checks_failed.append(f"Daily DD {daily_dd:.2f}% >= limit {rules['daily_dd_pct']}%")

    if rules["max_dd_pct"] and total_dd >= rules["max_dd_pct"]:
        checks_failed.append(f"Total DD {total_dd:.2f}% >= limit {rules['max_dd_pct']}%")

    if position_size_pct > 1.0:
        checks_failed.append(f"Position size {position_size_pct:.2f}% > 1% account risk")

    if rules["consistency_rule"] and total_profit_pct > 0:
        max_day = (rules["max_single_day_pct"] / 100) * total_profit_pct
        if day_profit_pct > max_day:
            checks_failed.append(f"Consistency rule: single day {day_profit_pct:.2f}% > {rules['max_single_day_pct']}% of total")

    if hold_time_sec < rules["min_hold_sec"]:
        checks_failed.append(f"Hold time {hold_time_sec}s < min {rules['min_hold_sec']}s")

    if win_rate < 65.0:
        checks_failed.append(f"Win rate {win_rate:.1f}% < required 65%")

    if checks_failed:
        return {"verdict": "BLOCKED", "reason": "; ".join(checks_failed), "checks_failed": checks_failed}

    return {"verdict": "APPROVED", "reason": None, "checks_failed": []}


@mcp.tool()
def get_daily_remaining(firm: str, current_daily_dd: float) -> float:
    """How much daily DD headroom remains before limit is hit."""
    rules = get_firm_rules(firm)
    return round(rules.get("daily_dd_pct", 5.0) - current_daily_dd, 2)


@mcp.tool()
def check_consistency(firm: str, day_profit_pct: float, total_profit_pct: float) -> dict:
    """Check if today's profit exceeds the consistency cap."""
    rules = get_firm_rules(firm)
    if not rules.get("consistency_rule", False):
        return {"ok": True, "rule_applies": False}

    cap_pct = rules.get("max_single_day_pct", 35)
    if total_profit_pct <= 0:
        return {"ok": True, "rule_applies": True, "cap_reached": False}

    max_allowed = (cap_pct / 100) * total_profit_pct
    ok = day_profit_pct <= max_allowed
    return {
        "ok": ok,
        "rule_applies": True,
        "cap_pct": cap_pct,
        "max_allowed_pct": round(max_allowed, 3),
        "current_pct": day_profit_pct,
    }


@mcp.tool()
def list_firms() -> list:
    """Return list of all supported prop firm names."""
    data = _load()
    return [k for k in data.keys() if k != "universally_banned"]


@mcp.tool()
def get_banned_practices() -> list:
    """Return list of universally banned trading practices."""
    return _load().get("universally_banned", [])


if __name__ == "__main__":
    mcp.run()
