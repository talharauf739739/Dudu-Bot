"""
MCP Server: mcp-tradingview
TradingView Webhook receiver + in-memory signal store.
Run standalone: python mcp_servers/mcp_tradingview/server.py
Webhook endpoint runs on TRADINGVIEW_WEBHOOK_PORT (default 8001).
"""

import os
import json
import hashlib
import hmac
from datetime import datetime
from typing import Optional
from collections import deque
from threading import Lock
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-tradingview")

WEBHOOK_SECRET = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "changeme")

# ── In-memory signal queue (thread-safe) ──────────────────────────────────────
_signals: dict[str, deque] = {}   # symbol -> deque of alert dicts
_lock = Lock()
MAX_SIGNALS_PER_SYMBOL = 20


def _add_signal(symbol: str, alert: dict):
    with _lock:
        if symbol not in _signals:
            _signals[symbol] = deque(maxlen=MAX_SIGNALS_PER_SYMBOL)
        _signals[symbol].appendleft(alert)


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature from TradingView Pine Script."""
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── FastAPI webhook receiver (started alongside MCP server) ───────────────────

def start_webhook_server():
    """Start a lightweight FastAPI server to receive TradingView alerts."""
    from fastapi import FastAPI, Request, HTTPException
    import uvicorn

    webhook_app = FastAPI(title="ForgeX TradingView Webhook")

    @webhook_app.post("/webhook/tradingview")
    async def receive_alert(request: Request):
        body = await request.body()
        sig = request.headers.get("X-Signature", "")
        if WEBHOOK_SECRET and not verify_signature(body, sig):
            raise HTTPException(status_code=401, detail="Invalid signature")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        symbol = data.get("symbol", "UNKNOWN").upper().replace("/", "")
        alert = {
            "symbol": symbol,
            "strategy": data.get("strategy", ""),
            "signal": data.get("signal", ""),       # BUY | SELL | CLOSE
            "pattern": data.get("pattern", ""),     # ORDER_BLOCK | EMA_CROSS etc.
            "score": float(data.get("score", 5.0)),
            "entry": float(data.get("entry", 0.0)),
            "timeframe": data.get("timeframe", "5min"),
            "direction": data.get("direction", ""),
            "received_at": datetime.utcnow().isoformat(),
        }
        _add_signal(symbol, alert)
        return {"status": "ok", "symbol": symbol}

    port = int(os.getenv("TRADINGVIEW_WEBHOOK_PORT", "8001"))
    uvicorn.run(webhook_app, host="0.0.0.0", port=port, log_level="warning")


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_latest_alert(symbol: str) -> Optional[dict]:
    """Return the most recent alert for a symbol."""
    sym = symbol.upper().replace("/", "")
    with _lock:
        q = _signals.get(sym)
        if q:
            return dict(q[0])
    return None


@mcp.tool()
def get_all_alerts(symbol: str) -> list:
    """Return all buffered alerts for a symbol (newest first)."""
    sym = symbol.upper().replace("/", "")
    with _lock:
        return [dict(a) for a in _signals.get(sym, [])]


@mcp.tool()
def get_active_symbols() -> list:
    """Return list of symbols that have received at least one alert today."""
    with _lock:
        return list(_signals.keys())


@mcp.tool()
def detect_order_block(symbol: str, timeframe: str) -> list:
    """
    Return any ORDER_BLOCK signals for the given symbol and timeframe.
    In production, this is confirmed by TradingView Pine Script.
    """
    alerts = get_all_alerts(symbol)
    return [
        a for a in alerts
        if "ORDER_BLOCK" in a.get("pattern", "").upper()
        and a.get("timeframe") == timeframe
    ]


@mcp.tool()
def check_ema_cross(symbol: str, timeframe: str, fast: int = 5, slow: int = 20) -> str:
    """
    Return CROSS_UP | CROSS_DOWN | NONE based on latest EMA_CROSS alert.
    """
    alerts = get_all_alerts(symbol)
    for a in alerts:
        if "EMA_CROSS" in a.get("pattern", "").upper() and a.get("timeframe") == timeframe:
            direction = a.get("direction", "").upper()
            if direction == "BUY":
                return "CROSS_UP"
            if direction == "SELL":
                return "CROSS_DOWN"
    return "NONE"


@mcp.tool()
def get_vwap(symbol: str) -> float:
    """Return VWAP level from latest VWAP alert (0.0 if unavailable)."""
    alerts = get_all_alerts(symbol)
    for a in alerts:
        if "VWAP" in a.get("pattern", "").upper():
            return float(a.get("entry", 0.0))
    return 0.0


@mcp.tool()
def score_signal(symbol: str) -> float:
    """Return the score of the latest signal (1-10). 0 if no signal."""
    alert = get_latest_alert(symbol)
    return float(alert.get("score", 0.0)) if alert else 0.0


if __name__ == "__main__":
    import threading
    t = threading.Thread(target=start_webhook_server, daemon=True)
    t.start()
    mcp.run()
