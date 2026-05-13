"""
Agent-06 — Recorder
Logs every trade (win, loss, blocked) to PostgreSQL.
Syncs to Google Drive. Sends Telegram notifications.
Triggers after every Agent-05 trade close.
"""

from datetime import datetime
from core.state import ForgeXState
from core.mcp_client import journal_mcp, telegram_mcp
from core.config import settings


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))
    logs.append("[Agent-06] Recorder writing trade to journal...")

    trade = state.get("selected_trade")
    verdict = state.get("risk_verdict", "PENDING")

    try:
        # Build trade record
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "instrument": trade["symbol"] if trade else "N/A",
            "direction": trade.get("direction", "N/A") if trade else "N/A",
            "strategy_id": trade.get("strategy_id", "N/A") if trade else "N/A",
            "timeframe": trade.get("timeframe", "5min") if trade else "N/A",
            "session": state.get("current_session", ""),
            "entry_price": trade.get("entry_price", 0.0) if trade else 0.0,
            "sl_price": trade.get("sl_price", 0.0) if trade else 0.0,
            "tp_price": trade.get("tp_price", 0.0) if trade else 0.0,
            "risk_rr": trade.get("risk_rr", 0.0) if trade else 0.0,
            "lot_size": trade.get("lot_size", 0.0) if trade else 0.0,
            "result": trade.get("result", "BLOCKED") if trade else "BLOCKED",
            "close_price": state.get("close_price"),
            "pnl_usd": state.get("pnl_usd"),
            "hold_time_s": state.get("hold_time_s"),
            "prop_firm": state.get("prop_firm", settings.ACTIVE_PROP_FIRM),
            "account_id": state.get("account_id", settings.ACTIVE_ACCOUNT_ID),
            "daily_dd_pct": state.get("daily_dd_pct", 0.0),
            "notes": state.get("risk_block_reason") if verdict == "BLOCKED" else None,
        }

        # Save to PostgreSQL
        trade_id = journal_mcp.call("log_trade", trade=record)
        logs.append(f"[Agent-06] Trade #{trade_id} saved to PostgreSQL")

        # Send Telegram notification
        result = record.get("result", "BLOCKED")
        pnl = record.get("pnl_usd") or 0.0

        if verdict == "BLOCKED":
            # Just log, no Telegram for blocks (avoid noise)
            pass
        elif state.get("trade_closed"):
            trade_for_tg = {**record, "instrument": record["instrument"]}
            telegram_mcp.call("send_trade_closed",
                              trade=trade_for_tg, result=result, pnl=pnl)
            logs.append(f"[Agent-06] Telegram notification sent: {result}")

        # Log to agent_logs table
        journal_mcp.call("log_agent_action",
                         agent="Agent-06",
                         message=f"Trade #{trade_id} logged: {result} ${pnl:+.2f}",
                         trade_id=trade_id if trade_id > 0 else None)

        # Update session counters
        session_trades = list(state.get("session_trades", []))
        session_trades.append(record)
        wins = state.get("session_wins", 0) + (1 if result == "WIN" else 0)
        losses = state.get("session_losses", 0) + (1 if result == "LOSS" else 0)

        return {
            **state,
            "trade_id_logged": trade_id,
            "journal_synced": False,       # Sheet sync happens at end-of-session
            "telegram_sent": True,
            "session_trades": session_trades,
            "session_wins": wins,
            "session_losses": losses,
            "agent_logs": logs,
        }

    except Exception as e:
        logs.append(f"[Agent-06] ERROR: {e}")
        return {**state, "agent_logs": logs, "error": str(e)}


def send_end_of_session_summary(state: ForgeXState) -> bool:
    """Called by Agent-08 at end of session. Builds and sends daily summary."""
    try:
        daily_stats = journal_mcp.call("get_daily_stats")
        balance_data = {"daily_dd_pct": state.get("daily_dd_pct", 0.0)}

        summary = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "session": state.get("current_session", ""),
            "duration_min": 0,
            "total_trades": daily_stats.get("total_trades", 0),
            "wins": daily_stats.get("wins", 0),
            "losses": daily_stats.get("losses", 0),
            "win_rate": daily_stats.get("win_rate", 0.0),
            "avg_rr": daily_stats.get("avg_rr", 0.0),
            "net_pnl": daily_stats.get("net_pnl", 0.0),
            "best_strategy": "N/A",
            "prop_firm_dd": {state.get("prop_firm", "N/A"): state.get("daily_dd_pct", 0.0)},
            "tomorrow_forecast": state.get("forecast_brief", ""),
        }
        telegram_mcp.call("send_daily_summary", summary=summary)

        # Export to Google Sheet
        journal_mcp.call("export_to_sheet", sheet_id=settings.GOOGLE_DRIVE_SHEET_ID)

        # Equity graph
        graph_path = journal_mcp.call("generate_equity_graph",
                                      account_id=state.get("account_id", ""))
        if graph_path:
            telegram_mcp.call("send_graph", image_path=graph_path,
                              caption="ForgeX Equity Curve")
        return True
    except Exception as e:
        print(f"[Agent-06] send_end_of_session_summary error: {e}")
        return False
