"""
Agent-07 — Forecaster
Analyzes journal data to detect performance patterns.
Predicts best next-session setups using Claude.
Runs at end of each trading session.
"""

import json
import anthropic
from core.state import ForgeXState
from core.mcp_client import journal_mcp, telegram_mcp
from core.config import settings

_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

STRATEGY_IDS = ["S-01", "S-02", "S-03", "S-04", "S-05",
                 "S-06", "S-07", "S-08", "S-09", "S-10"]


def _build_performance_report() -> dict:
    """Aggregate stats across all strategies for last 30 days."""
    report = {}
    for sid in STRATEGY_IDS:
        stats = journal_mcp.call("get_strategy_stats", strategy_id=sid, days=30)
        if stats.get("total_trades", 0) > 0:
            report[sid] = stats
    return report


def _flag_underperformers(report: dict) -> list:
    """Flag strategies with win rate below 60%."""
    return [
        sid for sid, stats in report.items()
        if stats.get("win_rate", 100) < 60.0
    ]


def _ask_claude_forecast(performance: dict, daily_stats: dict) -> str:
    """Use Claude to reason over performance data and produce a forecast."""
    prompt = f"""You are ForgeX AI's performance analyst agent.

Today's trading summary:
{json.dumps(daily_stats, indent=2)}

Strategy performance (last 30 days):
{json.dumps(performance, indent=2)}

Based on this data:
1. Which strategy has the highest probability of success tomorrow?
2. Which instrument and session combination is performing best?
3. Are there any strategies to avoid tomorrow?

Respond in 3-4 concise lines suitable for a Telegram message.
Start with: "Best window:" then "Top setup:" then "Avoid:" then "Watch:"
"""
    try:
        response = _client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=256,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Forecast unavailable: {e}"


def run(state: ForgeXState) -> dict:
    """End-of-session analysis. Returns updated state with forecast."""
    logs = list(state.get("agent_logs", []))
    logs.append("[Agent-07] Forecaster analyzing session data...")

    try:
        performance = _build_performance_report()
        daily_stats = journal_mcp.call("get_daily_stats")
        underperformers = _flag_underperformers(performance)

        if underperformers:
            logs.append(f"[Agent-07] Underperforming strategies (<60% WR): {underperformers}")

        forecast = _ask_claude_forecast(performance, daily_stats)
        logs.append(f"[Agent-07] Forecast generated: {forecast[:80]}...")

        # Send to Telegram as part of end-of-session summary (handled by Agent-06)
        # Store forecast in state for Agent-06 to include in daily brief
        return {
            **state,
            "forecast_brief": forecast,
            "performance_report": performance,
            "underperforming_strategies": underperformers,
            "agent_logs": logs,
        }

    except Exception as e:
        logs.append(f"[Agent-07] ERROR: {e}")
        return {**state, "agent_logs": logs, "error": str(e), "forecast_brief": ""}
