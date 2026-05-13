"""
MetaTrader 5 broker bridge.
Works with any MT5-compatible broker: Exness, IC Markets, Pepperstone, XM, etc.

NOTE: MetaTrader5 Python package only runs on Windows.
On macOS/Linux, import will fail — handled gracefully with a RuntimeError.
"""

from __future__ import annotations

import os
from typing import Optional

from brokers.base_broker import BaseBroker, BrokerOrder, BrokerPosition, AccountInfo


# Try importing MT5 — will fail on non-Windows
try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False


class MT5Broker(BaseBroker):
    """
    MetaTrader 5 broker implementation.
    Connects via the MT5 terminal installed on the local machine.

    Parameters
    ----------
    login    : MT5 account number
    password : account password
    server   : broker server string (e.g. "Exness-MT5Real8")
    path     : path to MetaEditor/terminal64.exe (optional if MT5 is in PATH)
    """

    def __init__(
        self,
        login:    int    = 0,
        password: str    = "",
        server:   str    = "",
        path:     str    = "",
        timeout:  int    = 60_000,
    ):
        if not _MT5_AVAILABLE:
            raise RuntimeError(
                "MetaTrader5 package is not installed or not supported on this OS. "
                "Install on Windows with: pip install MetaTrader5"
            )
        self.login    = login    or int(os.getenv("MT5_LOGIN",    "0"))
        self.password = password or os.getenv("MT5_PASSWORD",    "")
        self.server   = server   or os.getenv("MT5_SERVER",      "")
        self.path     = path     or os.getenv("MT5_TERMINAL_PATH", "")
        self.timeout  = timeout
        self._connected = False

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        kwargs = dict(login=self.login, password=self.password,
                      server=self.server, timeout=self.timeout)
        if self.path:
            kwargs["path"] = self.path

        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            raise ConnectionError(f"MT5 initialize failed: {err}")

        info = mt5.account_info()
        if info is None:
            raise ConnectionError("MT5 connected but account_info returned None")

        self._connected = True
        print(f"[MT5] Connected: #{info.login} | {info.server} | "
              f"Balance: {info.balance} {info.currency}")
        return True

    def disconnect(self):
        mt5.shutdown()
        self._connected = False

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        self._require_connection()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 account_info() returned None")
        return AccountInfo(
            balance     = info.balance,
            equity      = info.equity,
            margin      = info.margin,
            free_margin = info.margin_free,
            leverage    = info.leverage,
            currency    = info.currency,
        )

    # ── Orders ─────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol:    str,
        direction: str,
        lot_size:  float,
        sl_price:  float,
        tp_price:  float,
        comment:   str = "ForgeX AI",
    ) -> BrokerOrder:
        self._require_connection()

        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price_info = mt5.symbol_info_tick(symbol)
        if price_info is None:
            return BrokerOrder(ticket=0, symbol=symbol, direction=direction,
                               lot_size=lot_size, entry_price=0, sl_price=sl_price,
                               tp_price=tp_price, status="FAILED",
                               error=f"symbol_info_tick({symbol}) returned None")

        price = price_info.ask if direction == "BUY" else price_info.bid

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    lot_size,
            "type":      order_type,
            "price":     price,
            "sl":        sl_price,
            "tp":        tp_price,
            "deviation": 20,
            "magic":     20250101,
            "comment":   comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error() if result is None else result.comment
            return BrokerOrder(ticket=0, symbol=symbol, direction=direction,
                               lot_size=lot_size, entry_price=price,
                               sl_price=sl_price, tp_price=tp_price,
                               status="FAILED", error=str(err))

        return BrokerOrder(
            ticket      = result.order,
            symbol      = symbol,
            direction   = direction,
            lot_size    = lot_size,
            entry_price = result.price,
            sl_price    = sl_price,
            tp_price    = tp_price,
            status      = "OPEN",
        )

    def close_position(self, ticket: int) -> bool:
        self._require_connection()
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]
        close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == 0 else tick.ask

        request = {
            "action":   mt5.TRADE_ACTION_DEAL,
            "symbol":   p.symbol,
            "volume":   p.volume,
            "type":     close_type,
            "position": ticket,
            "price":    price,
            "deviation": 20,
            "magic":    20250101,
            "comment":  "ForgeX close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    def modify_sl_tp(self, ticket: int, sl_price: float, tp_price: float) -> bool:
        self._require_connection()
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   p.symbol,
            "sl":       sl_price,
            "tp":       tp_price,
            "position": ticket,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    # ── Positions ──────────────────────────────────────────────────────────────

    def get_open_positions(self) -> list[BrokerPosition]:
        self._require_connection()
        positions = mt5.positions_get()
        if positions is None:
            return []
        result = []
        for p in positions:
            result.append(BrokerPosition(
                ticket     = p.ticket,
                symbol     = p.symbol,
                direction  = "BUY" if p.type == 0 else "SELL",
                lot_size   = p.volume,
                open_price = p.price_open,
                sl_price   = p.sl,
                tp_price   = p.tp,
                pnl_usd    = p.profit,
                open_time  = str(p.time),
            ))
        return result

    def get_symbol_price(self, symbol: str) -> tuple[float, float]:
        self._require_connection()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 0.0, 0.0
        return tick.bid, tick.ask

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _require_connection(self):
        if not self._connected:
            raise RuntimeError("MT5 not connected. Call connect() first.")
