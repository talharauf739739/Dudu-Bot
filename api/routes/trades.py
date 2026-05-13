from fastapi import APIRouter, Query
from typing import Optional, List
from api.schemas.trade_schema import TradeOut
from core.mcp_client import journal_mcp

router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("/", response_model=List[dict])
def list_trades(
    limit: int = Query(default=50, le=500),
    prop_firm: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    strategy_id: Optional[str] = Query(default=None),
):
    trades = journal_mcp.call("get_recent_trades", limit=limit, prop_firm=prop_firm)
    if result:
        trades = [t for t in trades if t.get("result") == result.upper()]
    if strategy_id:
        trades = [t for t in trades if t.get("strategy_id") == strategy_id.upper()]
    return trades


@router.get("/today")
def todays_trades():
    return journal_mcp.call("get_daily_stats")


@router.get("/stats/{strategy_id}")
def strategy_stats(strategy_id: str, days: int = Query(default=30, le=90)):
    return journal_mcp.call("get_strategy_stats", strategy_id=strategy_id.upper(), days=days)
