"""
MCP Server: mcp-journal
SQLite trade journal — stores all bot history, viewable in Azure Data Studio.
DB file: data/forgex.db  (project root)
Run standalone: python mcp_servers/mcp_journal/server.py
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
import plotly.graph_objects as go
import plotly.io as pio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-journal")

# ── DB path ────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = str(_PROJECT_ROOT / "data" / "forgex.db")
SHEET_ID = os.getenv("GOOGLE_DRIVE_SHEET_ID", "")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db():
    """Create tables if they don't exist yet."""
    schema = (_PROJECT_ROOT / "database" / "schema.sql").read_text()
    with _get_conn() as conn:
        conn.executescript(schema)

_init_db()


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def log_trade(trade: dict) -> int:
    """Insert a trade record into the journal. Returns trade_id."""
    trade.setdefault("timestamp", datetime.utcnow().isoformat())
    trade.setdefault("result", None)
    trade.setdefault("close_price", None)
    trade.setdefault("pnl_usd", None)
    trade.setdefault("hold_time_s", None)
    trade.setdefault("daily_dd_pct", None)
    trade.setdefault("notes", None)

    sql = """
        INSERT INTO trades (
            timestamp, instrument, direction, strategy_id, timeframe, session,
            entry_price, sl_price, tp_price, risk_rr, lot_size,
            result, close_price, pnl_usd, hold_time_s,
            prop_firm, account_id, daily_dd_pct, notes
        ) VALUES (
            :timestamp, :instrument, :direction, :strategy_id, :timeframe, :session,
            :entry_price, :sl_price, :tp_price, :risk_rr, :lot_size,
            :result, :close_price, :pnl_usd, :hold_time_s,
            :prop_firm, :account_id, :daily_dd_pct, :notes
        )
    """
    try:
        with _get_conn() as conn:
            cur = conn.execute(sql, trade)
            return cur.lastrowid
    except Exception as e:
        print(f"[mcp-journal] log_trade error: {e}")
        return -1


@mcp.tool()
def update_trade_result(trade_id: int, result: str, pnl: float,
                        close_price: float, hold_time_s: int) -> bool:
    """Update trade result after position closes."""
    sql = """
        UPDATE trades
        SET result=:result, pnl_usd=:pnl, close_price=:close_price, hold_time_s=:hold_time_s
        WHERE trade_id=:trade_id
    """
    try:
        with _get_conn() as conn:
            conn.execute(sql, {
                "trade_id": trade_id, "result": result,
                "pnl": pnl, "close_price": close_price, "hold_time_s": hold_time_s,
            })
        return True
    except Exception as e:
        print(f"[mcp-journal] update_trade_result error: {e}")
        return False


@mcp.tool()
def get_strategy_stats(strategy_id: str, days: int = 30) -> dict:
    """Return win rate, avg R:R, and P&L stats for a strategy over N days."""
    try:
        with _get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) total,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) wins,
                       AVG(risk_rr) avg_rr,
                       AVG(pnl_usd) avg_pnl
                FROM trades
                WHERE strategy_id = ?
                  AND result IS NOT NULL
                  AND timestamp >= datetime('now', ? || ' days')
            """, (strategy_id, f"-{days}")).fetchone()

            if not row or not row["total"]:
                return {"strategy_id": strategy_id, "total_trades": 0, "win_rate": 0.0}

            best_session = conn.execute("""
                SELECT session FROM trades
                WHERE strategy_id = ? AND result IS NOT NULL
                GROUP BY session ORDER BY COUNT(*) DESC LIMIT 1
            """, (strategy_id,)).fetchone()

            best_instrument = conn.execute("""
                SELECT instrument FROM trades
                WHERE strategy_id = ? AND result IS NOT NULL
                GROUP BY instrument ORDER BY COUNT(*) DESC LIMIT 1
            """, (strategy_id,)).fetchone()

            total = row["total"]
            wins  = row["wins"] or 0
            return {
                "strategy_id":      strategy_id,
                "total_trades":     total,
                "wins":             wins,
                "losses":           total - wins,
                "win_rate":         round(wins / total * 100, 1),
                "avg_rr":           round(float(row["avg_rr"] or 0), 2),
                "avg_pnl":          round(float(row["avg_pnl"] or 0), 2),
                "best_session":     best_session["session"] if best_session else "N/A",
                "best_instrument":  best_instrument["instrument"] if best_instrument else "N/A",
            }
    except Exception as e:
        print(f"[mcp-journal] get_strategy_stats error: {e}")
        return {"strategy_id": strategy_id, "total_trades": 0, "win_rate": 0.0}


@mcp.tool()
def get_recent_trades(limit: int = 50, prop_firm: Optional[str] = None) -> list:
    """Return recent trades from the journal."""
    try:
        with _get_conn() as conn:
            if prop_firm:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE prop_firm=? ORDER BY timestamp DESC LIMIT ?",
                    (prop_firm, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[mcp-journal] get_recent_trades error: {e}")
        return []


@mcp.tool()
def get_daily_stats(date: Optional[str] = None) -> dict:
    """Return win rate and P&L stats for a given date (default: today)."""
    target = date or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        with _get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) total,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) wins,
                       SUM(pnl_usd) net_pnl,
                       AVG(risk_rr) avg_rr
                FROM trades
                WHERE DATE(timestamp) = ? AND result IS NOT NULL
            """, (target,)).fetchone()

            total = row["total"] or 0
            wins  = row["wins"] or 0
            return {
                "date":         target,
                "total_trades": total,
                "wins":         wins,
                "losses":       total - wins,
                "win_rate":     round(wins / total * 100, 1) if total else 0.0,
                "net_pnl":      round(float(row["net_pnl"] or 0), 2),
                "avg_rr":       round(float(row["avg_rr"] or 0), 2),
            }
    except Exception as e:
        print(f"[mcp-journal] get_daily_stats error: {e}")
        return {"date": target, "total_trades": 0}


@mcp.tool()
def generate_equity_graph(account_id: str, days: int = 30) -> str:
    """Generate equity curve graph. Returns path to saved PNG."""
    try:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT DATE(timestamp) AS day, SUM(pnl_usd) AS daily_pnl
                FROM trades
                WHERE account_id = ? AND result IS NOT NULL
                  AND timestamp >= datetime('now', ? || ' days')
                GROUP BY day ORDER BY day
            """, (account_id, f"-{days}")).fetchall()

        if not rows:
            return ""

        dates = [r["day"] for r in rows]
        cumulative, running = [], 0.0
        for r in rows:
            running += float(r["daily_pnl"] or 0)
            cumulative.append(round(running, 2))

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=cumulative,
            mode="lines+markers",
            line=dict(color="#00D4AA", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.1)",
            name="Equity Curve",
        ))
        fig.update_layout(
            title=f"ForgeX Equity Curve — {account_id}",
            xaxis_title="Date",
            yaxis_title="Cumulative P&L ($)",
            template="plotly_dark",
            height=400,
        )
        path = tempfile.mktemp(suffix=".png")
        pio.write_image(fig, path)
        return path
    except Exception as e:
        print(f"[mcp-journal] generate_equity_graph error: {e}")
        return ""


@mcp.tool()
def log_agent_action(agent: str, message: str, level: str = "INFO",
                     trade_id: Optional[int] = None) -> bool:
    """Log an agent action to the agent_logs table."""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_logs (agent, level, message, trade_id) VALUES (?,?,?,?)",
                (agent, level, message, trade_id)
            )
        return True
    except Exception as e:
        print(f"[mcp-journal] log_agent_action error: {e}")
        return False


@mcp.tool()
def log_drawdown(prop_firm: str, account_id: str,
                 daily_dd_pct: float, total_dd_pct: float, balance: float) -> bool:
    """Record a drawdown snapshot."""
    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT INTO drawdown_tracker
                    (prop_firm, account_id, daily_dd_pct, total_dd_pct, balance)
                VALUES (?,?,?,?,?)
            """, (prop_firm, account_id, daily_dd_pct, total_dd_pct, balance))
        return True
    except Exception as e:
        print(f"[mcp-journal] log_drawdown error: {e}")
        return False


@mcp.tool()
def export_to_sheet(sheet_id: str, date_range: Optional[str] = None) -> bool:
    """Export trade records to Google Sheet via gspread."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not creds_path:
            print("[mcp-journal] No Google credentials path set")
            return False

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id or SHEET_ID)
        ws = sh.sheet1

        trades = get_recent_trades(limit=500)
        if not trades:
            return True

        headers = list(trades[0].keys())
        rows = [[str(t.get(h, "")) for h in headers] for t in trades]
        ws.clear()
        ws.append_row(headers)
        ws.append_rows(rows)
        return True
    except Exception as e:
        print(f"[mcp-journal] export_to_sheet error: {e}")
        return False


if __name__ == "__main__":
    mcp.run()
