from fastapi import APIRouter, Query
from typing import Optional
from core.mcp_client import journal_mcp
from core.config import settings

router = APIRouter(prefix="/analytics", tags=["Analytics"])

STRATEGY_IDS = ["S-01", "S-02", "S-03", "S-04", "S-05",
                 "S-06", "S-07", "S-08", "S-09", "S-10"]


@router.get("/equity")
def equity_curve(account_id: Optional[str] = None, days: int = Query(default=30, le=90)):
    """Return equity curve data as JSON array."""
    acc = account_id or settings.ACTIVE_ACCOUNT_ID
    trades = journal_mcp.call("get_recent_trades", limit=500, prop_firm=None)
    if not trades:
        return {"data": [], "account_id": acc}

    from collections import defaultdict
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if t.get("result") in ("WIN", "LOSS", "BE") and t.get("pnl_usd") is not None:
            date_str = str(t["timestamp"])[:10]
            daily_pnl[date_str] += float(t["pnl_usd"])

    running = 0.0
    curve = []
    for date in sorted(daily_pnl.keys()):
        running += daily_pnl[date]
        curve.append({"date": date, "daily_pnl": round(daily_pnl[date], 2),
                      "cumulative_pnl": round(running, 2)})

    return {"data": curve[-days:], "account_id": acc}


@router.get("/winrate")
def win_rate_by_strategy():
    """Return win rate for all 10 strategies."""
    results = []
    for sid in STRATEGY_IDS:
        stats = journal_mcp.call("get_strategy_stats", strategy_id=sid, days=30)
        results.append({
            "strategy_id": sid,
            "win_rate": stats.get("win_rate", 0.0),
            "total_trades": stats.get("total_trades", 0),
            "avg_rr": stats.get("avg_rr", 0.0),
            "avg_pnl": stats.get("avg_pnl", 0.0),
            "best_session": stats.get("best_session", "N/A"),
            "best_instrument": stats.get("best_instrument", "N/A"),
        })
    return {"strategies": results}


@router.get("/drawdown")
def drawdown_tracker():
    """Return current drawdown status per prop firm."""
    from core.mcp_client import tradelocker
    balance = tradelocker.call("get_account_balance",
                               account_id=settings.ACTIVE_ACCOUNT_ID)
    return {
        "prop_firm": settings.ACTIVE_PROP_FIRM,
        "account_id": settings.ACTIVE_ACCOUNT_ID,
        "daily_dd_pct": balance.get("daily_dd_pct", 0.0),
        "daily_pnl": balance.get("daily_pnl", 0.0),
        "balance": balance.get("balance", 0.0),
        "equity": balance.get("equity", 0.0),
    }


@router.get("/performance")
def overall_performance(days: int = Query(default=30, le=90)):
    """High-level performance summary."""
    stats = journal_mcp.call("get_daily_stats")
    strategy_stats = [
        journal_mcp.call("get_strategy_stats", strategy_id=sid, days=days)
        for sid in STRATEGY_IDS
    ]
    active_strategies = [s for s in strategy_stats if s.get("total_trades", 0) > 0]
    best = max(active_strategies, key=lambda x: x.get("win_rate", 0), default={})
    return {
        "period_days": days,
        "today": stats,
        "best_strategy": best.get("strategy_id", "N/A"),
        "best_win_rate": best.get("win_rate", 0.0),
        "active_strategies": len(active_strategies),
    }
