"""
MCP Tool Caller — direct Python import mode for Phase 1 development.

Each MCP server exposes plain Python functions that are also registered
as FastMCP tools. In development we call those functions directly.
In production, swap MCPToolCaller.call() to use the MCP protocol transport.
"""

import importlib
import asyncio
from typing import Any

SERVER_MODULE_MAP: dict[str, str] = {
    "mcp-propfirm-kb":  "mcp_servers.mcp_propfirm_kb.server",
    "mcp-forexfactory": "mcp_servers.mcp_forexfactory.server",
    "mcp-tradelocker":  "mcp_servers.mcp_tradelocker.server",
    "mcp-deriv":        "mcp_servers.mcp_deriv.server",
    "mcp-tradingview":  "mcp_servers.mcp_tradingview.server",
    "mcp-telegram":     "mcp_servers.mcp_telegram.server",
    "mcp-journal":      "mcp_servers.mcp_journal.server",
}


class MCPToolCaller:
    """Calls MCP server tools as regular Python functions."""

    def __init__(self, server_name: str):
        if server_name not in SERVER_MODULE_MAP:
            raise ValueError(f"Unknown MCP server: {server_name}")
        self.server_name = server_name
        self._module = importlib.import_module(SERVER_MODULE_MAP[server_name])

    def call(self, tool_name: str, **kwargs) -> Any:
        func = getattr(self._module, tool_name)
        return func(**kwargs)

    async def acall(self, tool_name: str, **kwargs) -> Any:
        func = getattr(self._module, tool_name)
        if asyncio.iscoroutinefunction(func):
            return await func(**kwargs)
        return func(**kwargs)


# ── Pre-built callers (import once, use everywhere) ────────────────────────────

propfirm_mcp  = MCPToolCaller("mcp-propfirm-kb")
forex_mcp     = MCPToolCaller("mcp-forexfactory")
tradelocker   = MCPToolCaller("mcp-tradelocker")
deriv         = MCPToolCaller("mcp-deriv")
tradingview   = MCPToolCaller("mcp-tradingview")
telegram_mcp  = MCPToolCaller("mcp-telegram")
journal_mcp   = MCPToolCaller("mcp-journal")

# Active broker — swap here to switch between TradeLocker and Deriv
broker = deriv
