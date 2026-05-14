"""
Agent-03 — Strategy Oracle
Matches confirmed setup to best strategy from KB.
Uses Claude to reason over entry/SL/TP calculation.
Rejects if expected win rate < 65%.
"""

import json
from pathlib import Path
from core.state import ForgeXState
from core.mcp_client import journal_mcp
from core.config import settings
import core.llm_client as llm

_STRATEGY_PATH = (
    Path(__file__).parent.parent / "knowledge_base" / "strategies" / "strategies.json"
)
_strategy_kb: dict = {}


def _load_kb() -> dict:
    global _strategy_kb
    if not _strategy_kb:
        with open(_STRATEGY_PATH) as f:
            _strategy_kb = json.load(f)
    return _strategy_kb


def _get_strategy_win_rate(strategy_id: str) -> float:
    """Fetch live win rate from journal DB for this strategy."""
    try:
        stats = journal_mcp.call("get_strategy_stats", strategy_id=strategy_id, days=30)
        return stats.get("win_rate", 0.0)
    except Exception:
        kb = _load_kb()
        for s in kb["strategies"]:
            if s["id"] == strategy_id:
                return float(s["win_rate_min"])
        return 0.0


def _calculate_lot_size(account_balance: float, risk_pct: float, entry: float, sl: float) -> float:
    """Calculate lot size based on risk percentage."""
    if entry == 0 or sl == 0:
        return 0.01
    risk_usd = account_balance * (risk_pct / 100)
    pip_value_per_lot = 10.0
    pip_distance = abs(entry - sl)
    if pip_distance < 0.0001:
        pip_distance = 0.001
    lot = risk_usd / (pip_distance * 100000 * pip_value_per_lot / 100000)
    return round(max(0.01, min(lot, 10.0)), 2)


def _ask_claude(setup: dict, strategy: dict, account_balance: float) -> dict:
    """Use Groq LLM to calculate precise Entry/SL/TP and validate the trade."""
    prompt = f"""You are a professional Forex trading assistant for ForgeX AI.

Setup detected:
- Symbol: {setup['symbol']}
- Timeframe: {setup['timeframe']}
- Pattern: {setup['pattern']}
- Session: {setup['session']}
- Direction hint: {setup.get('direction', 'unclear')}
- Entry zone: {setup['entry_zone']}

Matched Strategy: {strategy['name']} ({strategy['id']})
- Entry rule: {strategy['entry_rule']}
- SL rule: {strategy['sl_rule']}
- TP rule: {strategy['tp_rule']}
- Target R:R: 1:{strategy['rr_min']} to 1:{strategy['rr_max']}

Account balance: ${account_balance:.2f}
Risk per trade: {settings.MAX_RISK_PER_TRADE_PCT}%

Return ONLY valid JSON in this exact format:
{{
  "direction": "BUY or SELL",
  "entry_price": 0.00000,
  "sl_price": 0.00000,
  "tp_price": 0.00000,
  "risk_rr": 0.0,
  "reasoning": "brief explanation"
}}

If the setup is unclear or invalid, return:
{{"direction": null, "entry_price": 0, "sl_price": 0, "tp_price": 0, "risk_rr": 0, "reasoning": "rejected: reason"}}
"""
    text = llm.ask(prompt, max_tokens=512, temperature=0.1, json_mode=True)
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    return json.loads(text)


def run(state: ForgeXState) -> dict:
    logs = list(state.get("agent_logs", []))
    setup = state.get("selected_setup")

    if not setup:
        logs.append("[Agent-03] No setup to process — skipping")
        return {**state, "selected_trade": None, "agent_logs": logs}

    logs.append(f"[Agent-03] Strategy Oracle processing: {setup['symbol']} {setup['pattern']}")

    try:
        kb = _load_kb()
        instrument_matrix = kb.get("instrument_matrix", {})
        symbol = setup["symbol"]
        timeframe = setup.get("timeframe", "5min")

        # Look up best strategy for this instrument and timeframe
        matrix_entry = instrument_matrix.get(symbol, {})
        strategy_id = matrix_entry.get(timeframe, "S-01")

        # Find strategy details
        strategy = next(
            (s for s in kb["strategies"] if s["id"] == strategy_id),
            kb["strategies"][0],
        )

        # Check historical win rate
        win_rate = _get_strategy_win_rate(strategy_id)
        if win_rate > 0 and win_rate < settings.MIN_WIN_RATE_PCT:
            logs.append(f"[Agent-03] REJECTED — {strategy_id} win rate {win_rate:.1f}% < {settings.MIN_WIN_RATE_PCT}%")
            return {**state, "selected_trade": None, "agent_logs": logs}

        # Claude calculates precise levels
        account_balance = state.get("account_balance", 10000.0)
        calc = _ask_claude(setup, strategy, account_balance)

        if not calc.get("direction") or calc["entry_price"] == 0:
            logs.append(f"[Agent-03] REJECTED by Claude: {calc.get('reasoning', 'invalid setup')}")
            return {**state, "selected_trade": None, "agent_logs": logs}

        lot_size = _calculate_lot_size(
            account_balance,
            settings.MAX_RISK_PER_TRADE_PCT,
            calc["entry_price"],
            calc["sl_price"],
        )

        trade = {
            "symbol": symbol,
            "direction": calc["direction"],
            "entry_price": calc["entry_price"],
            "sl_price": calc["sl_price"],
            "tp_price": calc["tp_price"],
            "strategy_id": strategy_id,
            "risk_rr": calc["risk_rr"],
            "timeframe": timeframe,
            "session": setup.get("session", ""),
            "lot_size": lot_size,
            "expected_win_rate": win_rate,
        }

        logs.append(
            f"[Agent-03] Trade selected: {symbol} {calc['direction']} "
            f"Entry:{calc['entry_price']} SL:{calc['sl_price']} TP:{calc['tp_price']} "
            f"R:R 1:{calc['risk_rr']}"
        )
        return {**state, "selected_trade": trade, "agent_logs": logs}

    except Exception as e:
        logs.append(f"[Agent-03] ERROR: {e}")
        return {**state, "selected_trade": None, "agent_logs": logs, "error": str(e)}
