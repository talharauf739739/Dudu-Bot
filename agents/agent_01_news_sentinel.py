"""
Agent-01 — News Sentinel
Monitors ForexFactory economic calendar and live news.
Publishes NEWS_SAFE or NEWS_BLOCK per currency to state.
Trigger: every 5 minutes during session hours.
"""

from core.state import ForgeXState
from core.mcp_client import forex_mcp

WATCHED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD"]
NEWS_BUFFER_MIN = 30


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))
    logs.append("[Agent-01] News Sentinel running...")

    try:
        events = forex_mcp.call("get_events_today")
        news_status = {}
        blocked_currencies = []

        for currency in WATCHED_CURRENCIES:
            is_blocked = forex_mcp.call("is_news_window",
                                        currency=currency,
                                        buffer_min=NEWS_BUFFER_MIN)
            if is_blocked:
                next_event = forex_mcp.call("get_next_high_impact", currency=currency)
                event_name = next_event.get("name", "HIGH impact event") if next_event else "HIGH impact event"
                event_time = next_event.get("time", "unknown") if next_event else "unknown"
                news_status[currency] = {
                    "status": "NEWS_BLOCK",
                    "event": event_name,
                    "event_time": event_time,
                }
                blocked_currencies.append(currency)
            else:
                news_status[currency] = {"status": "NEWS_SAFE"}

        if blocked_currencies:
            logs.append(f"[Agent-01] BLOCKED currencies: {blocked_currencies}")
        else:
            logs.append(f"[Agent-01] All currencies SAFE. Events today: {len(events)}")

        return {**state, "news_status": news_status, "agent_logs": logs}

    except Exception as e:
        logs.append(f"[Agent-01] ERROR: {e}")
        return {**state, "agent_logs": logs, "error": str(e)}
