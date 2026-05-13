"""
Agent-02 — Signal Hunter
Scans all 11 instruments for high-probability setups via TradingView MCP.
Only passes setups scoring >= MIN_SCORE (7.5) to Agent-03.
Trigger: on each TradingView webhook alert received.
"""

from core.state import ForgeXState
from core.mcp_client import tradingview, tradelocker
from core.config import settings

INSTRUMENTS = [
    "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US500",
    "USDCHF", "AUDUSD", "US30", "USDCAD", "EURJPY", "GBPJPY",
]
MIN_SCORE = settings.MIN_SIGNAL_SCORE
MAX_SPREAD_PIP = {"FOREX": 1.0, "INDEX": 2.0, "CROSS": 1.5}
INDEX_INSTRUMENTS = {"NAS100", "US500", "US30"}
CROSS_INSTRUMENTS = {"EURJPY", "GBPJPY"}


def _get_spread_type(symbol: str) -> str:
    if symbol in INDEX_INSTRUMENTS:
        return "INDEX"
    if symbol in CROSS_INSTRUMENTS:
        return "CROSS"
    return "FOREX"


def _is_spread_ok(symbol: str) -> bool:
    try:
        quote = tradelocker.call("get_instrument_price", symbol=symbol)
        spread = quote.get("spread", 999)
        max_spread = MAX_SPREAD_PIP[_get_spread_type(symbol)]
        return spread <= max_spread
    except Exception:
        return True  # default allow if can't check


def _is_currency_blocked(symbol: str, news_status: dict) -> bool:
    currency_map = {
        "EURUSD": ["EUR", "USD"], "GBPUSD": ["GBP", "USD"],
        "USDJPY": ["USD", "JPY"], "USDCHF": ["USD", "CHF"],
        "AUDUSD": ["AUD", "USD"], "USDCAD": ["USD", "CAD"],
        "EURJPY": ["EUR", "JPY"], "GBPJPY": ["GBP", "JPY"],
        "NAS100": ["USD"], "US500": ["USD"], "US30": ["USD"],
    }
    currencies = currency_map.get(symbol, [])
    for c in currencies:
        if news_status.get(c, {}).get("status") == "NEWS_BLOCK":
            return True
    return False


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))
    logs.append("[Agent-02] Signal Hunter scanning...")
    news_status = state.get("news_status", {})
    session = state.get("current_session", "SLEEP")

    try:
        all_signals = []

        for symbol in INSTRUMENTS:
            if _is_currency_blocked(symbol, news_status):
                logs.append(f"[Agent-02] {symbol} skipped — news block")
                continue

            alert = tradingview.call("get_latest_alert", symbol=symbol)
            if not alert:
                continue

            score = float(alert.get("score", 0))
            if score < MIN_SCORE:
                logs.append(f"[Agent-02] {symbol} score {score:.1f} < {MIN_SCORE} — discarded")
                continue

            if not _is_spread_ok(symbol):
                logs.append(f"[Agent-02] {symbol} spread too wide — skipped")
                continue

            signal = {
                "symbol": symbol,
                "timeframe": alert.get("timeframe", "5min"),
                "pattern": alert.get("pattern", ""),
                "score": score,
                "entry_zone": alert.get("entry", 0.0),
                "direction": alert.get("direction", ""),
                "session": session,
                "detected_at": alert.get("received_at", ""),
            }
            all_signals.append(signal)
            logs.append(f"[Agent-02] {symbol} PASSED — score {score:.1f}, pattern: {signal['pattern']}")

        # Sort by score descending — best setup first
        all_signals.sort(key=lambda x: x["score"], reverse=True)
        selected = all_signals[0] if all_signals else None

        if selected:
            logs.append(f"[Agent-02] Best setup: {selected['symbol']} score {selected['score']:.1f}")
        else:
            logs.append("[Agent-02] No qualifying setups found this scan")

        return {
            **state,
            "active_signals": all_signals,
            "selected_setup": selected,
            "agent_logs": logs,
        }

    except Exception as e:
        logs.append(f"[Agent-02] ERROR: {e}")
        return {**state, "agent_logs": logs, "error": str(e)}
