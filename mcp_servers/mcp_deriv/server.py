"""
MCP Server: mcp-deriv
Deriv WebSocket API — Multipliers for Forex/Index trading.
Demo account: VRTC6144147 | Live account: CR3988560
Run standalone: python mcp_servers/mcp_deriv/server.py
"""

import asyncio
import json
import os
from typing import Optional
import websockets
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-deriv")

_MODE       = os.getenv("DERIV_MODE", "demo")
API_KEY     = os.getenv("DERIV_API_KEY") if _MODE == "demo" else os.getenv("DERIV_API_KEY_REAL", "")
APP_ID      = os.getenv("DERIV_APP_ID", "1089")
WS_URL      = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
ACCOUNT_ID  = os.getenv("DERIV_ACCOUNT_ID") if _MODE == "demo" else os.getenv("DERIV_ACCOUNT_ID_REAL", "")

# Bot instruments → Deriv symbol names
SYMBOL_MAP: dict[str, str] = {
    "EURUSD":  "frxEURUSD",
    "GBPUSD":  "frxGBPUSD",
    "USDJPY":  "frxUSDJPY",
    "USDCHF":  "frxUSDCHF",
    "AUDUSD":  "frxAUDUSD",
    "USDCAD":  "frxUSDCAD",
    "XAUUSD":  "frxXAUUSD",
    "NAS100":  "OTC_NDX",
    "US30":    "OTC_DJI",
    "GER40":   "OTC_GDAXI",
    "UK100":   "frxUK100",
}


async def _ws_call(payload: dict) -> dict:
    """Connect, authorize, send one payload, return response."""
    try:
        async with websockets.connect(WS_URL, ping_timeout=15) as ws:
            await ws.send(json.dumps({"authorize": API_KEY}))
            auth = json.loads(await ws.recv())
            if auth.get("error"):
                return {"error": auth["error"]}

            await ws.send(json.dumps(payload))
            resp = json.loads(await ws.recv())
            return resp
    except Exception as e:
        return {"error": {"message": str(e)}}


def _call(payload: dict) -> dict:
    return asyncio.run(_ws_call(payload))


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def place_order(
    symbol: str,
    direction: str,
    stake: float,
    multiplier: int = 100,
    stop_loss_usd: Optional[float] = None,
    take_profit_usd: Optional[float] = None,
) -> dict:
    """
    Place a Multiplier order on Deriv.
    symbol: EURUSD | GBPUSD | XAUUSD | NAS100 | US30 | etc.
    direction: 'buy' | 'sell'
    stake: USD amount to stake (e.g. 10.0)
    multiplier: leverage multiplier (10 | 20 | 50 | 100 | 200 | 500)
    stop_loss_usd: max loss in USD (optional)
    take_profit_usd: target profit in USD (optional)
    """
    deriv_sym = SYMBOL_MAP.get(symbol.upper(), symbol)
    contract_type = "MULTUP" if direction.lower() == "buy" else "MULTDOWN"

    params: dict = {
        "amount":        stake,
        "basis":         "stake",
        "contract_type": contract_type,
        "currency":      "USD",
        "multiplier":    multiplier,
        "product_type":  "basic",
        "symbol":        deriv_sym,
    }

    limit_order: dict = {}
    if stop_loss_usd is not None:
        limit_order["stop_loss"] = {"order_type": "stop", "order_amount": stop_loss_usd}
    if take_profit_usd is not None:
        limit_order["take_profit"] = {"order_type": "limit", "order_amount": take_profit_usd}
    if limit_order:
        params["limit_order"] = limit_order

    resp = _call({"buy": 1, "price": stake, "parameters": params})

    if resp.get("error"):
        return {"order_id": "", "symbol": symbol, "status": "error",
                "error": resp["error"].get("message", str(resp["error"]))}

    buy = resp.get("buy", {})
    return {
        "order_id":    str(buy.get("contract_id", "")),
        "symbol":      symbol,
        "direction":   direction.upper(),
        "stake":       stake,
        "multiplier":  multiplier,
        "entry_price": buy.get("start_time", 0),
        "status":      "filled",
    }


@mcp.tool()
def get_open_positions(account_id: str = "") -> list:
    """Return all open Multiplier contracts."""
    resp = _call({"portfolio": 1, "contract_type": ["MULTUP", "MULTDOWN"]})
    if resp.get("error"):
        return []

    contracts = resp.get("portfolio", {}).get("contracts", [])
    positions = []
    for c in contracts:
        positions.append({
            "order_id":       str(c.get("contract_id")),
            "symbol":         c.get("symbol"),
            "direction":      "BUY" if c.get("contract_type") == "MULTUP" else "SELL",
            "entry_price":    c.get("buy_price", 0.0),
            "current_price":  c.get("current_spot", 0.0),
            "stake":          c.get("buy_price", 0.0),
            "unrealized_pnl": c.get("profit", 0.0),
            "multiplier":     c.get("multiplier", 0),
        })
    return positions


@mcp.tool()
def close_position(order_id: str, partial_size: Optional[float] = None) -> dict:
    """Close an open Multiplier contract by contract_id."""
    resp = _call({"sell": int(order_id), "price": 0})
    if resp.get("error"):
        return {"order_id": order_id, "status": "error",
                "error": resp["error"].get("message", str(resp["error"]))}

    sell = resp.get("sell", {})
    return {
        "order_id":    order_id,
        "status":      "closed",
        "close_price": sell.get("sold_for", 0.0),
        "pnl":         sell.get("sold_for", 0.0),
    }


@mcp.tool()
def get_account_balance(account_id: str = "") -> dict:
    """Return account balance and P&L."""
    resp = _call({"balance": 1})
    if resp.get("error"):
        return {"account_id": ACCOUNT_ID, "balance": 0.0, "daily_pnl": 0.0, "daily_dd_pct": 0.0}

    bal = resp.get("balance", {})
    balance = float(bal.get("balance", 0))
    return {
        "account_id":   bal.get("loginid", ACCOUNT_ID),
        "balance":      balance,
        "equity":       balance,
        "currency":     bal.get("currency", "USD"),
        "daily_pnl":    0.0,
        "daily_dd_pct": 0.0,
        "used_margin":  0.0,
        "free_margin":  balance,
    }


@mcp.tool()
def get_daily_pnl(account_id: str = "") -> float:
    """Return today's realized P&L from profit table."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp = _call({
        "profit_table": 1,
        "description":  1,
        "sort":         "DESC",
        "date_from":    f"{today} 00:00:00",
    })
    if resp.get("error"):
        return 0.0

    transactions = resp.get("profit_table", {}).get("transactions", [])
    return round(sum(float(t.get("sell_price", 0)) - float(t.get("buy_price", 0))
                     for t in transactions), 2)


@mcp.tool()
def get_instrument_price(symbol: str) -> dict:
    """Return current bid/ask for a symbol."""
    deriv_sym = SYMBOL_MAP.get(symbol.upper(), symbol)
    resp = _call({"ticks": deriv_sym})
    if resp.get("error"):
        return {"symbol": symbol, "bid": 0.0, "ask": 0.0, "spread": 0.0}

    tick = resp.get("tick", {})
    bid  = float(tick.get("bid", tick.get("quote", 0)))
    ask  = float(tick.get("ask", tick.get("quote", 0)))
    return {
        "symbol": symbol,
        "bid":    bid,
        "ask":    ask,
        "spread": round(ask - bid, 5),
    }


@mcp.tool()
def modify_sl_tp(order_id: str, new_sl: float, new_tp: float) -> bool:
    """Update stop loss and take profit on an open Multiplier contract."""
    resp = _call({
        "contract_update": 1,
        "contract_id":     int(order_id),
        "limit_order": {
            "stop_loss":   {"order_type": "stop",  "order_amount": new_sl},
            "take_profit": {"order_type": "limit", "order_amount": new_tp},
        },
    })
    return not bool(resp.get("error"))


if __name__ == "__main__":
    mcp.run()
