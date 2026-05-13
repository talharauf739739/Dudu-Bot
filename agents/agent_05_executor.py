"""
Agent-05 — Executor
Only activates after Agent-04 APPROVED.
Places and manages full trade lifecycle on TradeLocker DEMO.
Monitors position every 30 seconds.
Partial close at 1:1 R:R, moves SL to BE, closes on TP/SL.
"""

import time
from datetime import datetime
from core.state import ForgeXState
from core.mcp_client import tradelocker

MONITOR_INTERVAL_SEC = 30
MAX_MONITOR_LOOPS = 480       # 4 hours max hold


def _calculate_breakeven_sl(direction: str, entry: float) -> float:
    buffer = 0.00003           # 0.3 pip buffer past entry
    return entry + buffer if direction == "BUY" else entry - buffer


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))

    if state.get("risk_verdict") != "APPROVED":
        logs.append("[Agent-05] Verdict not APPROVED — Executor idle")
        return {**state, "agent_logs": logs}

    trade = state.get("selected_trade")
    if not trade:
        logs.append("[Agent-05] No trade to execute")
        return {**state, "agent_logs": logs}

    symbol   = trade["symbol"]
    direction = trade["direction"]
    lot_size = trade["lot_size"]
    sl       = trade["sl_price"]
    tp       = trade["tp_price"]
    entry    = trade["entry_price"]
    rr       = trade.get("risk_rr", 2.0)

    logs.append(f"[Agent-05] Placing order: {symbol} {direction} lot={lot_size} SL={sl} TP={tp}")

    try:
        # ── Place order ───────────────────────────────────────────────────────
        order = tradelocker.call(
            "place_order",
            symbol=symbol,
            direction=direction,
            size=lot_size,
            sl=sl,
            tp=tp,
        )

        if order.get("status") == "error":
            logs.append(f"[Agent-05] Order failed: {order.get('error')}")
            return {**state, "agent_logs": logs, "error": order.get("error")}

        order_id = order["order_id"]
        filled_price = order.get("filled_price", entry)
        opened_at = datetime.utcnow()
        logs.append(f"[Agent-05] Order #{order_id} filled at {filled_price}")

        # ── Position management loop ──────────────────────────────────────────
        partial_closed = False
        sl_at_be = False
        result = "OPEN"
        close_price = 0.0
        pnl_usd = 0.0

        # Partial close target (1:1 R:R)
        sl_distance = abs(filled_price - sl)
        partial_tp = (filled_price + sl_distance) if direction == "BUY" else (filled_price - sl_distance)

        for _ in range(MAX_MONITOR_LOOPS):
            time.sleep(MONITOR_INTERVAL_SEC)

            positions = tradelocker.call("get_open_positions")
            pos = next((p for p in positions if str(p["order_id"]) == str(order_id)), None)

            if pos is None:
                # Position no longer open — closed by TP or SL
                logs.append(f"[Agent-05] Position #{order_id} closed externally")
                break

            current_price = pos["current_price"]
            unrealized = pos["unrealized_pnl"]
            hold_sec = int((datetime.utcnow() - opened_at).total_seconds())

            # ── Partial close at 1:1 ─────────────────────────────────────────
            if not partial_closed:
                hit_partial = (
                    (direction == "BUY" and current_price >= partial_tp) or
                    (direction == "SELL" and current_price <= partial_tp)
                )
                if hit_partial:
                    partial_size = round(lot_size * 0.5, 2)
                    tradelocker.call("close_position", order_id=order_id, partial_size=partial_size)
                    logs.append(f"[Agent-05] Partial close {partial_size} lots at {current_price} (1:1 hit)")
                    partial_closed = True

            # ── Move SL to breakeven after 1:1 ───────────────────────────────
            if partial_closed and not sl_at_be:
                be_sl = _calculate_breakeven_sl(direction, filled_price)
                tradelocker.call("modify_sl_tp", order_id=order_id, new_sl=be_sl, new_tp=tp)
                logs.append(f"[Agent-05] SL moved to breakeven: {be_sl}")
                sl_at_be = True

            # ── Check if TP or SL hit ─────────────────────────────────────────
            tp_hit = (direction == "BUY" and current_price >= tp) or \
                     (direction == "SELL" and current_price <= tp)
            sl_hit = (direction == "BUY" and current_price <= sl) or \
                     (direction == "SELL" and current_price >= sl)

            if tp_hit or sl_hit:
                close_result = tradelocker.call("close_position", order_id=order_id)
                close_price = close_result.get("close_price", current_price)
                pnl_usd = close_result.get("pnl", unrealized)
                result = "WIN" if tp_hit else "LOSS"
                hold_time_s = int((datetime.utcnow() - opened_at).total_seconds())
                logs.append(f"[Agent-05] Position closed: {result} PnL=${pnl_usd:.2f} at {close_price}")
                break
        else:
            # Max hold time reached — force close
            close_result = tradelocker.call("close_position", order_id=order_id)
            close_price = close_result.get("close_price", 0.0)
            pnl_usd = close_result.get("pnl", 0.0)
            result = "WIN" if pnl_usd >= 0 else "LOSS"
            logs.append(f"[Agent-05] Max hold reached — force closed. {result} ${pnl_usd:.2f}")

        hold_time_s = int((datetime.utcnow() - opened_at).total_seconds())

        return {
            **state,
            "order_result": order,
            "active_order_id": order_id,
            "trade_closed": True,
            "close_price": close_price,
            "pnl_usd": pnl_usd,
            "hold_time_s": hold_time_s,
            "selected_trade": {
                **trade,
                "result": result,
                "close_price": close_price,
                "pnl_usd": pnl_usd,
                "hold_time_s": hold_time_s,
            },
            "agent_logs": logs,
        }

    except Exception as e:
        logs.append(f"[Agent-05] ERROR: {e}")
        return {**state, "agent_logs": logs, "error": str(e)}
