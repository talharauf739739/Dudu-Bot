"""
Abstract broker interface.
All broker implementations must inherit and implement these methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class BrokerOrder:
    ticket:     int
    symbol:     str
    direction:  str        # BUY | SELL
    lot_size:   float
    entry_price: float
    sl_price:   float
    tp_price:   float
    status:     str        # PENDING | OPEN | CLOSED | FAILED
    error:      str = ""


@dataclass
class BrokerPosition:
    ticket:      int
    symbol:      str
    direction:   str
    lot_size:    float
    open_price:  float
    sl_price:    float
    tp_price:    float
    pnl_usd:     float
    open_time:   str


@dataclass
class AccountInfo:
    balance:    float
    equity:     float
    margin:     float
    free_margin: float
    leverage:   int
    currency:   str


class BaseBroker(ABC):
    """Abstract base for all broker integrations."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to broker. Returns True on success."""
        ...

    @abstractmethod
    def disconnect(self):
        """Close broker connection."""
        ...

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Return current account balance, equity, margin."""
        ...

    @abstractmethod
    def place_order(
        self,
        symbol:    str,
        direction: str,
        lot_size:  float,
        sl_price:  float,
        tp_price:  float,
        comment:   str = "ForgeX AI",
    ) -> BrokerOrder:
        """Place a market order. Returns BrokerOrder with ticket and status."""
        ...

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        """Close an open position by ticket. Returns True on success."""
        ...

    @abstractmethod
    def modify_sl_tp(
        self,
        ticket:    int,
        sl_price:  float,
        tp_price:  float,
    ) -> bool:
        """Modify SL/TP on an open position."""
        ...

    @abstractmethod
    def get_open_positions(self) -> list[BrokerPosition]:
        """Return all currently open positions."""
        ...

    @abstractmethod
    def get_symbol_price(self, symbol: str) -> tuple[float, float]:
        """Return (bid, ask) for a symbol."""
        ...

    def get_position(self, ticket: int) -> Optional[BrokerPosition]:
        """Find a specific position by ticket (default: linear scan)."""
        for pos in self.get_open_positions():
            if pos.ticket == ticket:
                return pos
        return None
