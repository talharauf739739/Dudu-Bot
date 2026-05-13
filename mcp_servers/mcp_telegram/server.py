"""
MCP Server: mcp-telegram
Telegram Bot API — real-time trade notifications and daily briefs.
Run standalone: python mcp_servers/mcp_telegram/server.py
"""

import os
import requests
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-telegram")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[mcp-telegram] No credentials. Would send: {text[:80]}")
        return False
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[mcp-telegram] send error: {e}")
        return False


def _send_photo(image_path: str, caption: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[mcp-telegram] Would send photo: {image_path}")
        return False
    try:
        with open(image_path, "rb") as img:
            resp = requests.post(
                f"{BASE_URL}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"photo": img},
                timeout=15,
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"[mcp-telegram] send_photo error: {e}")
        return False


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def send_trade_opened(trade: dict) -> bool:
    """Send a notification when a trade is opened."""
    emoji = "🟢" if trade.get("direction") == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>TRADE OPENED — {trade.get('instrument')}</b>\n"
        f"Direction: {trade.get('direction')}\n"
        f"Entry: {trade.get('entry_price')}\n"
        f"SL: {trade.get('sl_price')}  |  TP: {trade.get('tp_price')}\n"
        f"R:R: 1:{trade.get('risk_rr')}  |  Lot: {trade.get('lot_size')}\n"
        f"Strategy: {trade.get('strategy_id')}  |  {trade.get('session')}\n"
        f"Firm: {trade.get('prop_firm')}"
    )
    return _send(msg)


@mcp.tool()
def send_trade_closed(trade: dict, result: str, pnl: float) -> bool:
    """Send a notification when a trade is closed."""
    if result == "WIN":
        emoji = "✅"
    elif result == "LOSS":
        emoji = "❌"
    else:
        emoji = "⚖️"
    sign = "+" if pnl >= 0 else ""
    msg = (
        f"{emoji} <b>TRADE CLOSED — {trade.get('instrument')} {result}</b>\n"
        f"P&L: {sign}${pnl:.2f}\n"
        f"Close: {trade.get('close_price', 'N/A')}  |  "
        f"Hold: {trade.get('hold_time_s', 0)//60}min\n"
        f"Strategy: {trade.get('strategy_id')}  |  Firm: {trade.get('prop_firm')}"
    )
    return _send(msg)


@mcp.tool()
def send_daily_summary(summary: dict) -> bool:
    """Send end-of-session daily summary."""
    win_rate = summary.get("win_rate", 0)
    wr_emoji = "🔥" if win_rate >= 70 else "✅" if win_rate >= 60 else "⚠️"
    dd_lines = "\n".join(
        f"  {firm}: {pct:.1f}% used"
        for firm, pct in summary.get("prop_firm_dd", {}).items()
    )
    sign = "+" if summary.get("net_pnl", 0) >= 0 else ""
    msg = (
        f"📊 <b>FORGEX DAILY BRIEF — {summary.get('date')}</b>\n"
        f"{'─'*30}\n"
        f"Session: {summary.get('session')}  |  Duration: {summary.get('duration_min')}min\n\n"
        f"<b>PERFORMANCE</b>\n"
        f"Trades: {summary.get('total_trades')}  |  "
        f"Wins: {summary.get('wins')}  |  "
        f"Losses: {summary.get('losses')}\n"
        f"{wr_emoji} Win Rate: {win_rate:.1f}%  |  "
        f"Net P&L: {sign}${summary.get('net_pnl', 0):.2f}\n\n"
        f"<b>DRAWDOWN TRACKER</b>\n{dd_lines}\n\n"
        f"<b>BEST STRATEGY</b>: {summary.get('best_strategy', 'N/A')}\n\n"
        f"<b>TOMORROW FORECAST</b> (Agent-07):\n"
        f"{summary.get('tomorrow_forecast', 'No forecast available')}"
    )
    return _send(msg)


@mcp.tool()
def send_news_block(event: str, currency: str) -> bool:
    """Send alert when a news block is triggered."""
    msg = (
        f"⛔ <b>NEWS BLOCK</b>\n"
        f"Event: {event}\n"
        f"Currency: {currency}\n"
        f"Trading paused for 30min window."
    )
    return _send(msg)


@mcp.tool()
def send_circuit_breaker(reason: str) -> bool:
    """Send alert when circuit breaker triggers."""
    msg = f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\nReason: {reason}\nAll trading paused for today."
    return _send(msg)


@mcp.tool()
def send_graph(image_path: str, caption: str) -> bool:
    """Send a chart image to Telegram."""
    return _send_photo(image_path, caption)


@mcp.tool()
def send_message(text: str) -> bool:
    """Send a plain text message."""
    return _send(text)


if __name__ == "__main__":
    mcp.run()
