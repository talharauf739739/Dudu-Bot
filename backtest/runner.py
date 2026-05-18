"""
Backtest Runner — runs all 10 strategies across all instruments and timeframes.
Results are saved to SQLite (backtest_results table) and indexed into RAG.
Run: python -m backtest.runner
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from backtest.data_fetcher import fetch_ohlc
from backtest.engine import BacktestEngine
from backtest.signals import (
    s01_ict_ob_fvg, s02_ema_rsi, s03_smc_bos_choch,
    s04_vwap_rejection, s05_london_breakout,
    s07_keltner_rsi, s09_macd_rsi, s10_heikin_ashi,
)
from rag.vector_store import index_backtest_result

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH      = str(_PROJECT_ROOT / "data" / "forgex.db")
_KB_PATH      = _PROJECT_ROOT / "knowledge_base" / "strategies" / "strategies.json"
_RULES_PATH   = _PROJECT_ROOT / "knowledge_base" / "prop_firms" / "rules.json"

SIGNAL_FN_MAP = {
    "S-01": s01_ict_ob_fvg,
    "S-02": s02_ema_rsi,
    "S-03": s03_smc_bos_choch,
    "S-04": s04_vwap_rejection,
    "S-05": s05_london_breakout,
    "S-07": s07_keltner_rsi,
    "S-09": s09_macd_rsi,
    "S-10": s10_heikin_ashi,
}

TF_DAYS = {
    "1min":  7,
    "5min":  60,
    "15min": 60,
    "1h":    180,
    "1hr":   180,
}


def _ensure_schema():
    """Add backtest_results table if not present."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            strategy_id     TEXT    NOT NULL,
            symbol          TEXT    NOT NULL,
            timeframe       TEXT    NOT NULL,
            prop_firm       TEXT    NOT NULL,
            total_trades    INTEGER NOT NULL DEFAULT 0,
            wins            INTEGER NOT NULL DEFAULT 0,
            losses          INTEGER NOT NULL DEFAULT 0,
            win_rate        REAL    NOT NULL DEFAULT 0,
            net_pnl_usd     REAL    NOT NULL DEFAULT 0,
            net_pnl_pct     REAL    NOT NULL DEFAULT 0,
            avg_rr          REAL    NOT NULL DEFAULT 0,
            max_drawdown_pct REAL   NOT NULL DEFAULT 0,
            profit_factor   REAL    NOT NULL DEFAULT 0,
            blocked_trades  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_strategy ON backtest_results(strategy_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_symbol   ON backtest_results(symbol)")
    conn.commit()
    conn.close()


def _save_result(result_dict: dict):
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        INSERT INTO backtest_results
            (strategy_id, symbol, timeframe, prop_firm,
             total_trades, wins, losses, win_rate,
             net_pnl_usd, net_pnl_pct, avg_rr,
             max_drawdown_pct, profit_factor, blocked_trades)
        VALUES
            (:strategy, :symbol, :timeframe, :prop_firm,
             :total_trades, :wins, :losses, :win_rate,
             :net_pnl_usd, :net_pnl_pct, :avg_rr,
             :max_drawdown_pct, :profit_factor, :blocked_trades)
    """, result_dict)
    conn.commit()
    conn.close()


def run_all(
    prop_firm: str = "FundedNext",
    account_size: float = 6000.0,
    risk_pct: float = 1.0,
    verbose: bool = True,
) -> list[dict]:
    """
    Run every strategy on every instrument/timeframe combo.
    Returns list of result dicts. Saves to DB + RAG.
    """
    _ensure_schema()

    strategies = json.loads(_KB_PATH.read_text()).get("strategies", [])
    rules_data  = json.loads(_RULES_PATH.read_text())
    prop_rules  = rules_data.get(prop_firm, rules_data.get("FundedNext", {
        "daily_dd_pct": 5.0, "max_dd_pct": 10.0
    }))

    all_results = []
    total = sum(len(s.get("instruments", [])) for s in strategies if s["id"] in SIGNAL_FN_MAP)
    done  = 0

    for strategy in strategies:
        sid      = strategy["id"]
        sig_fn   = SIGNAL_FN_MAP.get(sid)
        if sig_fn is None:
            continue

        instruments = strategy.get("instruments", [])
        timeframes  = strategy.get("timeframes", ["5min"])

        for symbol in instruments:
            for tf in timeframes:
                done += 1
                days = TF_DAYS.get(tf, 60)

                if verbose:
                    print(f"[{done}/{total}] {sid} | {symbol} | {tf} ...", end=" ", flush=True)

                df = fetch_ohlc(symbol, tf, days=days)
                if df.empty or len(df) < 30:
                    if verbose: print("NO DATA")
                    continue

                try:
                    signals = sig_fn(df, symbol)
                except Exception as e:
                    if verbose: print(f"SIGNAL ERROR: {e}")
                    continue

                engine = BacktestEngine(
                    account_size=account_size,
                    risk_per_trade_pct=risk_pct,
                    prop_firm_rules=prop_rules,
                )

                bt = engine.run(
                    df=df,
                    signals=signals,
                    strategy_id=sid,
                    symbol=symbol,
                    timeframe=tf,
                    prop_firm_name=prop_firm,
                )

                result = bt.to_dict()
                if verbose:
                    print(f"trades={result['total_trades']} wr={result['win_rate']}% "
                          f"pnl=${result['net_pnl_usd']} pf={result['profit_factor']}")

                if result["total_trades"] > 0:
                    _save_result(result)
                    index_backtest_result(result)
                    all_results.append(result)

    print(f"\n[Runner] Done. {len(all_results)} results saved to DB + RAG.")
    return all_results


def get_best_strategies(min_win_rate: float = 60.0, min_trades: int = 5) -> list[dict]:
    """Query SQLite for top performing strategy/symbol combos."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT strategy_id, symbol, timeframe, win_rate, net_pnl_usd,
               avg_rr, profit_factor, total_trades
        FROM backtest_results
        WHERE win_rate >= ? AND total_trades >= ?
        ORDER BY profit_factor DESC, win_rate DESC
        LIMIT 20
    """, (min_win_rate, min_trades)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_strategy_summary(strategy_id: str) -> dict:
    """Get aggregated backtest stats for one strategy across all symbols."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT
            COUNT(*)                    AS runs,
            SUM(total_trades)           AS total_trades,
            AVG(win_rate)               AS avg_win_rate,
            SUM(net_pnl_usd)            AS total_pnl,
            AVG(avg_rr)                 AS avg_rr,
            AVG(profit_factor)          AS avg_pf,
            MAX(max_drawdown_pct)       AS worst_dd
        FROM backtest_results
        WHERE strategy_id = ?
    """, (strategy_id,)).fetchone()
    conn.close()
    if not row or not row["runs"]:
        return {}
    return dict(row)


if __name__ == "__main__":
    results = run_all()
    print("\n=== TOP STRATEGIES ===")
    best = get_best_strategies()
    for r in best[:10]:
        print(f"  {r['strategy_id']:5} | {r['symbol']:8} | {r['timeframe']:5} | "
              f"WR={r['win_rate']}% | PnL=${r['net_pnl_usd']} | PF={r['profit_factor']}")
