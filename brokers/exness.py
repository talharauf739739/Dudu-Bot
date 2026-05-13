"""
Exness-specific broker configuration.
Wraps MT5Broker with Exness server names, symbol mappings, and pip values.
"""

import os
from brokers.mt5_bridge import MT5Broker
from brokers.base_broker import BrokerOrder, AccountInfo


# Exness symbol names differ from standard Forex notation
EXNESS_SYMBOL_MAP = {
    # Forex pairs
    "EURUSD": "EURUSDm",      # micro accounts use 'm' suffix; remove if standard
    "GBPUSD": "GBPUSDm",
    "USDJPY": "USDJPYm",
    "AUDUSD": "AUDUSDm",
    "USDCAD": "USDCADm",
    "NZDUSD": "NZDUSDm",
    # Indices (Exness uses these names)
    "NAS100": "USTEC",        # NASDAQ 100 Cash
    "US30":   "DJ30",         # Dow Jones 30
    "SPX500": "SP500",        # S&P 500
    "UK100":  "UK100",
    "DE40":   "GER40",
    # Metals
    "XAUUSD": "XAUUSDm",
    "XAGUSD": "XAGUSDm",
}

# Pip value per standard lot for each symbol (approximate, USD account)
EXNESS_PIP_VALUES = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 9.1,
    "AUDUSD": 10.0,
    "USDCAD": 7.7,
    "NAS100": 1.0,    # $1 per point per lot
    "US30":   1.0,
    "SPX500": 1.0,
    "XAUUSD": 10.0,   # $1 per 0.01 move per lot
}

EXNESS_SERVERS = {
    "real":  "Exness-MT5Real8",
    "demo":  "Exness-MT5Trial8",
}


def get_exness_symbol(standard_symbol: str) -> str:
    """Convert ForgeX symbol name to Exness MT5 symbol name."""
    mapped = EXNESS_SYMBOL_MAP.get(standard_symbol.upper(), standard_symbol)
    # Strip 'm' suffix for standard/pro accounts (set via env)
    if os.getenv("EXNESS_ACCOUNT_TYPE", "standard").lower() != "micro":
        mapped = mapped.rstrip("m") if mapped.endswith("m") else mapped
    return mapped


def get_exness_pip_value(symbol: str) -> float:
    return EXNESS_PIP_VALUES.get(symbol.upper(), 10.0)


class ExnessBroker(MT5Broker):
    """
    Exness MT5 broker with symbol mapping pre-applied.

    Set in .env:
        EXNESS_LOGIN, EXNESS_PASSWORD, EXNESS_SERVER (real|demo)
    """

    def __init__(self, demo: bool = True):
        server_key = "demo" if demo else "real"
        super().__init__(
            login    = int(os.getenv("EXNESS_LOGIN",    "0")),
            password = os.getenv("EXNESS_PASSWORD",     ""),
            server   = os.getenv("EXNESS_SERVER", EXNESS_SERVERS[server_key]),
            path     = os.getenv("MT5_TERMINAL_PATH",  ""),
        )
        self.demo = demo

    def place_order(
        self,
        symbol:    str,
        direction: str,
        lot_size:  float,
        sl_price:  float,
        tp_price:  float,
        comment:   str = "ForgeX AI",
    ) -> BrokerOrder:
        """Translates ForgeX symbol to Exness symbol before placing order."""
        exness_sym = get_exness_symbol(symbol)
        order = super().place_order(exness_sym, direction, lot_size,
                                    sl_price, tp_price, comment)
        order.symbol = symbol  # restore original name in result
        return order

    def get_symbol_price(self, symbol: str) -> tuple[float, float]:
        exness_sym = get_exness_symbol(symbol)
        return super().get_symbol_price(exness_sym)
