"""
MCP Server: mcp-journal
PostgreSQL trade journal + Google Drive/Sheets sync.
Run standalone: python mcp_servers/mcp_journal/server.py
"""

import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Optional
import psycopg2
import psycopg2.extras
import plotly.graph_objects as go
import plotly.io as pio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-journal")

DATABASE_URL   = os.getenv("DATABASE_URL", "")
SHEET_ID       = os.getenv("GOOGLE_DRIVE_SHEET_ID", "")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def log_trade(trade: dict) -> int:
    """Insert a trade record into PostgreSQL. Returns trade_id."""
    sql = """
        INSERT INTO trades (
            timestamp, instrument, direction, strategy_id, timeframe, session,
            entry_price, sl_price, tp_price, risk_rr, lot_size,
            result, close_price, pnl_usd, hold_time_s,
            prop_firm, account_id, daily_dd_pct, notes
        ) VALUES (
            %(timestamp)s, %(instrument)s, %(direction)s, %(strategy_id)s,
            %(timeframe)s, %(session)s, %(entry_price)s, %(sl_price)s,
            %(tp_price)s, %(risk_rr)s, %(lot_size)s,
            %(result)s, %(close_price)s, %(pnl_usd)s, %(hold_time_s)s,
            %(prop_firm)s, %(account_id)s, %(daily_dd_pct)s, %(notes)s
        ) RETURNING trade_id
    """
    trade.setdefault("timestamp", datetime.utcnow().isoformat())
    trade.setdefault("result", None)
    trade.setdefault("close_price", None)
    trade.setdefault("pnl_usd", None)
    trade.setdefault("hold_time_s", None)
    trade.setdefault("daily_dd_pct", None)
    trade.setdefault("notes", None)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, trade)
                return cur.fetchone()[0]
    except Exception as e:
        print(f"[mcp-journal] log_trade error: {e}")
        return -1


@mcp.tool()
def update_trade_result(trade_id: int, result: str, pnl: float,
                        close_price: float, hold_time_s: int) -> bool:
    """Update trade result after position closes."""
    sql = """
        UPDATE trades SET result=%(result)s, pnl_usd=%(pnl)s,
        close_price=%(close_price)s, hold_time_s=%(hold_time_s)s
        WHERE trade_id=%(trade_id)s
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
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
    sql = """
        SELECT COUNT(*) total,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) wins,
               AVG(risk_rr) avg_rr,
               AVG(pnl_usd) avg_pnl,
               MODE() WITHIN GROUP (ORDER BY session) best_session,
               MODE() WITHIN GROUP (ORDER BY instrument) best_instrument
        FROM trades
        WHERE strategy_id = %s
          AND result IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '%s days'
    """
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (strategy_id, days))
                row = cur.fetchone()
                if not row or not row["total"]:
                    return {"strategy_id": strategy_id, "total_trades": 0, "win_rate": 0.0}
                total = row["total"]
                wins = row["wins"] or 0
                return {
                    "strategy_id": strategy_id,
                    "total_trades": total,
                    "wins": wins,
                    "losses": total - wins,
                    "win_rate": round(wins / total * 100, 1),
                    "avg_rr": round(float(row["avg_rr"] or 0), 2),
                    "avg_pnl": round(float(row["avg_pnl"] or 0), 2),
                    "best_session": row["best_session"] or "N/A",
                    "best_instrument": row["best_instrument"] or "N/A",
                }
    except Exception as e:
        print(f"[mcp-journal] get_strategy_stats error: {e}")
        return {"strategy_id": strategy_id, "total_trades": 0, "win_rate": 0.0}


@mcp.tool()
def get_recent_trades(limit: int = 50, prop_firm: Optional[str] = None) -> list:
    """Return recent trades from the journal."""
    where = "WHERE prop_firm = %s" if prop_firm else ""
    params = (prop_firm, limit) if prop_firm else (limit,)
    sql = f"""
        SELECT * FROM trades {where}
        ORDER BY timestamp DESC LIMIT %s
    """
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[mcp-journal] get_recent_trades error: {e}")
        return []


@mcp.tool()
def get_daily_stats(date: Optional[str] = None) -> dict:
    """Return win rate and P&L stats for a given date (default: today)."""
    target = date or datetime.utcnow().strftime("%Y-%m-%d")
    sql = """
        SELECT COUNT(*) total,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) wins,
               SUM(pnl_usd) net_pnl,
               AVG(risk_rr) avg_rr
        FROM trades
        WHERE DATE(timestamp) = %s AND result IS NOT NULL
    """
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (target,))
                row = cur.fetchone()
                total = row["total"] or 0
                wins = row["wins"] or 0
                return {
                    "date": target,
                    "total_trades": total,
                    "wins": wins,
                    "losses": total - wins,
                    "win_rate": round(wins / total * 100, 1) if total else 0.0,
                    "net_pnl": round(float(row["net_pnl"] or 0), 2),
                    "avg_rr": round(float(row["avg_rr"] or 0), 2),
                }
    except Exception as e:
        print(f"[mcp-journal] get_daily_stats error: {e}")
        return {"date": target, "total_trades": 0}


@mcp.tool()
def generate_equity_graph(account_id: str, days: int = 30) -> str:
    """Generate equity curve graph. Returns path to saved PNG."""
    sql = """
        SELECT DATE(timestamp) AS day, SUM(pnl_usd) AS daily_pnl
        FROM trades
        WHERE account_id = %s AND result IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '%s days'
        GROUP BY day ORDER BY day
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (account_id, days))
                rows = cur.fetchall()

        if not rows:
            return ""

        dates = [r[0].strftime("%m/%d") for r in rows]
        cumulative = []
        running = 0.0
        for r in rows:
            running += float(r[1] or 0)
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
        rows = [list(str(t.get(h, "")) for h in headers) for t in trades]
        ws.clear()
        ws.append_row(headers)
        ws.append_rows(rows)
        return True
    except Exception as e:
        print(f"[mcp-journal] export_to_sheet error: {e}")
        return False


@mcp.tool()
def log_agent_action(agent: str, message: str, level: str = "INFO",
                     trade_id: Optional[int] = None) -> bool:
    """Log an agent action to the agent_logs table."""
    sql = """
        INSERT INTO agent_logs (agent, level, message, trade_id)
        VALUES (%s, %s, %s, %s)
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (agent, level, message, trade_id))
        return True
    except Exception as e:
        print(f"[mcp-journal] log_agent_action error: {e}")
        return False


if __name__ == "__main__":
    mcp.run()
