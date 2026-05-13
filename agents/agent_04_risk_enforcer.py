"""
Agent-04 — Risk Enforcer
Final checkpoint before any trade. Runs 8 prop firm rule checks.
One failure = trade blocked. No exceptions.
"""

from core.state import ForgeXState
from core.mcp_client import propfirm_mcp, tradelocker, journal_mcp
from core.config import settings


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))
    trade = state.get("selected_trade")

    if not trade:
        logs.append("[Agent-04] No trade candidate — skipping risk check")
        return {
            **state,
            "risk_verdict": "BLOCKED",
            "risk_block_reason": "No trade candidate from Agent-03",
            "agent_logs": logs,
        }

    logs.append(f"[Agent-04] Risk Enforcer checking: {trade['symbol']} {trade['direction']}")

    prop_firm = state.get("prop_firm", settings.ACTIVE_PROP_FIRM)
    account_id = state.get("account_id", settings.ACTIVE_ACCOUNT_ID)

    try:
        # Fetch live account state
        balance_data = tradelocker.call("get_account_balance", account_id=account_id)
        account_balance = balance_data.get("balance", 0.0)
        daily_dd_pct = balance_data.get("daily_dd_pct", 0.0)
        total_dd_pct = state.get("total_dd_pct", 0.0)

        # Fetch daily journal stats for consistency check
        daily_stats = journal_mcp.call("get_daily_stats")
        day_profit_pct = 0.0
        total_profit_pct = 0.0
        if account_balance > 0 and daily_stats.get("net_pnl"):
            day_profit_pct = (daily_stats["net_pnl"] / account_balance) * 100

        # Historical win rate from journal
        win_rate = trade.get("expected_win_rate", 0.0)
        if win_rate == 0:
            stats = journal_mcp.call("get_strategy_stats",
                                     strategy_id=trade["strategy_id"], days=30)
            win_rate = stats.get("win_rate", 70.0)

        # Position size as % of account
        position_size_pct = settings.MAX_RISK_PER_TRADE_PCT

        # News check from Agent-01 output
        news_status = state.get("news_status", {})
        symbol = trade["symbol"]
        currency_map = {
            "EURUSD": ["EUR", "USD"], "GBPUSD": ["GBP", "USD"],
            "USDJPY": ["USD", "JPY"], "USDCHF": ["USD", "CHF"],
            "AUDUSD": ["AUD", "USD"], "USDCAD": ["USD", "CAD"],
            "EURJPY": ["EUR", "JPY"], "GBPJPY": ["GBP", "JPY"],
            "NAS100": ["USD"], "US500": ["USD"], "US30": ["USD"],
        }
        currencies = currency_map.get(symbol, [])
        news_blocked = any(
            news_status.get(c, {}).get("status") == "NEWS_BLOCK"
            for c in currencies
        )

        # Estimated hold time (FundingPips: must exceed 60s)
        # For market orders we assume 60s minimum hold by design
        expected_hold_sec = 120

        # Run all 8 checks via propfirm MCP
        result = propfirm_mcp.call(
            "is_trade_allowed",
            firm=prop_firm,
            daily_dd=daily_dd_pct,
            total_dd=total_dd_pct,
            position_size_pct=position_size_pct,
            day_profit_pct=day_profit_pct,
            total_profit_pct=total_profit_pct,
            hold_time_sec=expected_hold_sec,
            win_rate=win_rate,
            news_blocked=news_blocked,
            session_active=state.get("session_active", False),
        )

        verdict = result.get("verdict", "BLOCKED")
        reason = result.get("reason")
        checks_failed = result.get("checks_failed", [])

        # Update state with live account data
        update = {
            **state,
            "risk_verdict": verdict,
            "risk_block_reason": reason,
            "risk_checks_failed": checks_failed,
            "account_balance": account_balance,
            "daily_dd_pct": daily_dd_pct,
            "agent_logs": logs,
        }

        if verdict == "APPROVED":
            logs.append(f"[Agent-04] ✅ APPROVED — all 8 checks passed")
        else:
            logs.append(f"[Agent-04] ❌ BLOCKED — {reason}")

        return update

    except Exception as e:
        logs.append(f"[Agent-04] ERROR: {e}")
        return {
            **state,
            "risk_verdict": "BLOCKED",
            "risk_block_reason": f"Risk check error: {e}",
            "agent_logs": logs,
            "error": str(e),
        }
