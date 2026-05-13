"""
MCP Server: mcp-tradelocker
TradeLocker REST API bridge — DEMO accounts only.
Run standalone: python mcp_servers/mcp_tradelocker/server.py
"""

import os
import requests
from typing import Optional
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-tradelocker")

BASE_URL   = os.getenv("TRADELOCKER_BASE_URL", "https://demo.tradelocker.com/backend-api")
EMAIL      = os.getenv("TRADELOCKER_EMAIL", "")
PASSWORD   = os.getenv("TRADELOCKER_PASSWORD", "")
SERVER     = os.getenv("TRADELOCKER_SERVER", "OSP-DEMO")
ACCOUNT_ID = os.getenv("TRADELOCKER_ACCOUNT_ID", "")

_token: Optional[str] = None
_token_expiry: Optional[datetime] = None


def _auth() -> str:
    """Authenticate and return Bearer token. Caches until expiry."""
    global _token, _token_expiry
    now = datetime.utcnow()
    if _token and _token_expiry and now < _token_expiry:
        return _token
    resp = requests.post(
        f"{BASE_URL}/auth/jwt/token",
        json={"email": EMAIL, "password": PASSWORD, "server": SERVER},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["accessToken"]
    _token_expiry = datetime.utcnow().replace(hour=21, minute=0, second=0)  # refresh daily
    return _token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_auth()}", "Content-Type": "application/json"}


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def place_order(symbol: str, direction: str, size: float, sl: float, tp: float) -> dict:
    """
    Place a market order on the DEMO account.
    direction: 'buy' | 'sell'
    Returns OrderResult dict.
    """
    payload = {
        "tradableInstrumentId": symbol,
        "type": "market",
        "side": direction.lower(),
        "qty": size,
        "stopLoss": sl,
        "takeProfit": tp,
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/trade/accounts/{ACCOUNT_ID}/orders",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "order_id": str(data.get("id", "")),
            "symbol": symbol,
            "direction": direction.upper(),
            "filled_price": data.get("price", 0.0),
            "lot_size": size,
            "sl": sl,
            "tp": tp,
            "status": data.get("status", "filled"),
        }
    except Exception as e:
        return {"order_id": "", "symbol": symbol, "status": "error", "error": str(e)}


@mcp.tool()
def get_open_positions(account_id: str = "") -> list:
    """Return all currently open positions for the account."""
    acc = account_id or ACCOUNT_ID
    try:
        resp = requests.get(
            f"{BASE_URL}/trade/accounts/{acc}/positions",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        positions = resp.json().get("positions", [])
        return [
            {
                "order_id": str(p.get("id")),
                "symbol": p.get("tradableInstrumentId"),
                "direction": p.get("side", "").upper(),
                "entry_price": p.get("openPrice", 0.0),
                "current_price": p.get("currentPrice", 0.0),
                "sl": p.get("stopLoss", 0.0),
                "tp": p.get("takeProfit", 0.0),
                "lot_size": p.get("qty", 0.0),
                "unrealized_pnl": p.get("unrealizedPl", 0.0),
                "hold_time_s": p.get("holdingTime", 0),
            }
            for p in positions
        ]
    except Exception as e:
        print(f"[mcp-tradelocker] get_open_positions error: {e}")
        return []


@mcp.tool()
def close_position(order_id: str, partial_size: Optional[float] = None) -> dict:
    """Close a position fully or partially."""
    try:
        payload = {"qty": partial_size} if partial_size else {}
        resp = requests.delete(
            f"{BASE_URL}/trade/accounts/{ACCOUNT_ID}/positions/{order_id}",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "order_id": order_id,
            "status": "closed",
            "close_price": data.get("closePrice", 0.0),
            "pnl": data.get("realizedPl", 0.0),
        }
    except Exception as e:
        return {"order_id": order_id, "status": "error", "error": str(e)}


@mcp.tool()
def modify_sl_tp(order_id: str, new_sl: float, new_tp: float) -> bool:
    """Modify stop loss and take profit on an open position."""
    try:
        resp = requests.patch(
            f"{BASE_URL}/trade/accounts/{ACCOUNT_ID}/positions/{order_id}",
            json={"stopLoss": new_sl, "takeProfit": new_tp},
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[mcp-tradelocker] modify_sl_tp error: {e}")
        return False


@mcp.tool()
def get_account_balance(account_id: str = "") -> dict:
    """Return account balance, equity, margin, and daily P&L."""
    acc = account_id or ACCOUNT_ID
    try:
        resp = requests.get(
            f"{BASE_URL}/trade/accounts/{acc}",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("account", {})
        balance = data.get("balance", 0.0)
        equity = data.get("equity", balance)
        daily_pnl = data.get("todayRealizedPl", 0.0)
        daily_dd_pct = round(abs(min(daily_pnl, 0)) / balance * 100, 3) if balance > 0 else 0
        return {
            "account_id": acc,
            "balance": balance,
            "equity": equity,
            "used_margin": data.get("usedMargin", 0.0),
            "free_margin": data.get("freeMargin", 0.0),
            "daily_pnl": daily_pnl,
            "daily_dd_pct": daily_dd_pct,
        }
    except Exception as e:
        print(f"[mcp-tradelocker] get_account_balance error: {e}")
        return {"account_id": acc, "balance": 0.0, "daily_pnl": 0.0, "daily_dd_pct": 0.0}


@mcp.tool()
def get_daily_pnl(account_id: str = "") -> float:
    """Return today's realized P&L in USD."""
    return get_account_balance(account_id).get("daily_pnl", 0.0)


@mcp.tool()
def get_instrument_price(symbol: str) -> dict:
    """Return current bid/ask for a symbol."""
    try:
        resp = requests.get(
            f"{BASE_URL}/trade/quotes",
            params={"symbol": symbol},
            headers=_headers(),
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "symbol": symbol,
            "bid": data.get("bid", 0.0),
            "ask": data.get("ask", 0.0),
            "spread": round(data.get("ask", 0.0) - data.get("bid", 0.0), 5),
        }
    except Exception as e:
        return {"symbol": symbol, "bid": 0.0, "ask": 0.0, "spread": 0.0}


if __name__ == "__main__":
    mcp.run()
