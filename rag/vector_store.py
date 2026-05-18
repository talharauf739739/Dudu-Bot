"""
RAG Vector Store — ChromaDB + sentence-transformers (all local, no API key).
Stores:
  1. Strategy rules (from knowledge_base/strategies/strategies.json)
  2. Backtest results (from SQLite after backtest runs)
  3. Live trade outcomes (updated after every closed trade)

Agent-03 queries this before asking Groq — grounded decisions, not guesses.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

_PROJECT_ROOT  = Path(__file__).parent.parent
_CHROMA_PATH   = str(_PROJECT_ROOT / "data" / "chroma")
_STRATEGY_FILE = _PROJECT_ROOT / "knowledge_base" / "strategies" / "strategies.json"
_DB_PATH       = str(_PROJECT_ROOT / "data" / "forgex.db")

_EMBED_MODEL   = "all-MiniLM-L6-v2"   # 80MB, runs fully local

# ── Singletons ─────────────────────────────────────────────────────────────────
_client: Optional[chromadb.PersistentClient] = None
_embedder: Optional[SentenceTransformer] = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=_CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(_EMBED_MODEL)
    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    return _get_embedder().encode(texts, show_progress_bar=False).tolist()


def _get_collection(name: str):
    return _get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# ── Strategy Knowledge Indexing ────────────────────────────────────────────────

def index_strategies(force: bool = False) -> int:
    """Index all strategy rules into ChromaDB. Returns number of docs indexed."""
    col = _get_collection("strategies")

    if not force and col.count() >= 10:
        return col.count()

    data = json.loads(_STRATEGY_FILE.read_text())
    strategies = data.get("strategies", [])

    docs, ids, metas = [], [], []
    for s in strategies:
        text = (
            f"Strategy {s['id']}: {s['name']}. "
            f"Instruments: {', '.join(s.get('instruments', []))}. "
            f"Timeframes: {', '.join(s.get('timeframes', []))}. "
            f"Sessions: {', '.join(s.get('sessions', []))}. "
            f"Patterns: {', '.join(s.get('patterns', []))}. "
            f"Entry rule: {s.get('entry_rule', '')}. "
            f"SL rule: {s.get('sl_rule', '')}. "
            f"TP rule: {s.get('tp_rule', '')}. "
            f"Expected win rate: {s.get('win_rate_min', 0)}-{s.get('win_rate_max', 0)}%. "
            f"R:R range: {s.get('rr_min', 0)}-{s.get('rr_max', 0)}."
        )
        docs.append(text)
        ids.append(s["id"])
        metas.append({
            "strategy_id": s["id"],
            "name": s["name"],
            "timeframes": ",".join(s.get("timeframes", [])),
            "instruments": ",".join(s.get("instruments", [])),
            "sessions": ",".join(s.get("sessions", [])),
        })

    embeddings = _embed(docs)
    col.upsert(documents=docs, ids=ids, metadatas=metas, embeddings=embeddings)
    return len(docs)


# ── Backtest Result Indexing ───────────────────────────────────────────────────

def index_backtest_result(result: dict) -> str:
    """Index one backtest result dict into ChromaDB. Returns doc id."""
    col = _get_collection("backtest_results")

    doc_id = f"{result['strategy']}_{result['symbol']}_{result.get('timeframe','?')}"
    text = (
        f"Backtest: Strategy {result['strategy']} on {result['symbol']} "
        f"({result.get('timeframe','?')} timeframe, {result.get('prop_firm','?')} rules). "
        f"Trades: {result.get('total_trades', 0)}, "
        f"Win rate: {result.get('win_rate', 0)}%, "
        f"Net P&L: ${result.get('net_pnl_usd', 0)}, "
        f"Avg R:R: {result.get('avg_rr', 0)}, "
        f"Max DD: {result.get('max_drawdown_pct', 0)}%, "
        f"Profit factor: {result.get('profit_factor', 0)}. "
        f"Blocked trades: {result.get('blocked_trades', 0)}."
    )

    embeddings = _embed([text])
    col.upsert(
        documents=[text],
        ids=[doc_id],
        metadatas=[{
            "strategy_id":   result["strategy"],
            "symbol":        result["symbol"],
            "timeframe":     result.get("timeframe", ""),
            "win_rate":      str(result.get("win_rate", 0)),
            "net_pnl_usd":   str(result.get("net_pnl_usd", 0)),
            "profit_factor": str(result.get("profit_factor", 0)),
        }],
        embeddings=embeddings,
    )
    return doc_id


def index_live_trade(trade: dict) -> str:
    """Index a closed live trade result for future RAG context."""
    col = _get_collection("live_trades")

    doc_id = f"trade_{trade.get('trade_id', id(trade))}"
    text = (
        f"Live trade: {trade.get('strategy_id','?')} on {trade.get('instrument','?')} "
        f"({trade.get('direction','?')}, {trade.get('session','?')} session). "
        f"Result: {trade.get('result','?')}, P&L: ${trade.get('pnl_usd', 0)}, "
        f"R:R: {trade.get('risk_rr', 0)}, "
        f"Entry: {trade.get('entry_price', 0)}, SL: {trade.get('sl_price', 0)}, "
        f"TP: {trade.get('tp_price', 0)}. "
        f"Notes: {trade.get('notes', 'none')}."
    )

    embeddings = _embed([text])
    col.upsert(
        documents=[text],
        ids=[doc_id],
        metadatas=[{
            "strategy_id": trade.get("strategy_id", ""),
            "instrument":  trade.get("instrument", ""),
            "result":      trade.get("result", ""),
            "session":     trade.get("session", ""),
        }],
        embeddings=embeddings,
    )
    return doc_id


def sync_live_trades_from_db() -> int:
    """Pull all closed trades from SQLite and index them into RAG."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trades WHERE result IS NOT NULL ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
        conn.close()
    except Exception:
        return 0

    for row in rows:
        index_live_trade(dict(row))
    return len(rows)


# ── Query Interface ────────────────────────────────────────────────────────────

def query_strategies(
    question: str,
    instrument: str = "",
    session: str = "",
    n_results: int = 3,
) -> list[dict]:
    """
    Query strategy knowledge. Returns top N relevant strategy docs with metadata.
    Used by Agent-03 to ground strategy selection.
    """
    col = _get_collection("strategies")
    if col.count() == 0:
        index_strategies()

    where = {}
    if instrument:
        where["instruments"] = {"$contains": instrument.upper()}
    if session:
        where["sessions"] = {"$contains": session.upper()}

    query_emb = _embed([question])
    try:
        results = col.query(
            query_embeddings=query_emb,
            n_results=min(n_results, col.count()),
            where=where if where else None,
        )
    except Exception:
        results = col.query(query_embeddings=query_emb, n_results=min(n_results, col.count()))

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return [{"text": d, "meta": m} for d, m in zip(docs, metas)]


def query_backtest_results(
    strategy_id: str = "",
    symbol: str = "",
    n_results: int = 5,
) -> list[dict]:
    """Query historical backtest results for a strategy/symbol combo."""
    col = _get_collection("backtest_results")
    if col.count() == 0:
        return []

    question = f"Performance of {strategy_id} on {symbol}"
    query_emb = _embed([question])
    where = {}
    if strategy_id:
        where["strategy_id"] = strategy_id
    if symbol:
        where["symbol"] = symbol

    try:
        results = col.query(
            query_embeddings=query_emb,
            n_results=min(n_results, col.count()),
            where=where if where else None,
        )
    except Exception:
        results = col.query(query_embeddings=query_emb, n_results=min(n_results, col.count()))

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return [{"text": d, "meta": m} for d, m in zip(docs, metas)]


def query_full_context(
    instrument: str,
    session: str,
    direction_hint: str = "",
    n_strategies: int = 3,
) -> str:
    """
    Single call used by Agent-03:
    Returns a formatted context string with relevant strategies + their backtest performance.
    """
    question = f"Best strategy for {instrument} during {session} session {direction_hint}"

    strategies = query_strategies(question, instrument=instrument, session=session, n_results=n_strategies)
    context_parts = ["=== STRATEGY KNOWLEDGE ==="]
    for s in strategies:
        context_parts.append(s["text"])
        sid = s["meta"].get("strategy_id", "")
        bt_results = query_backtest_results(strategy_id=sid, symbol=instrument, n_results=2)
        if bt_results:
            context_parts.append("  Historical performance:")
            for r in bt_results:
                context_parts.append(f"  {r['text']}")

    return "\n".join(context_parts)


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def bootstrap():
    """Index strategies and sync live trades. Run once on startup."""
    n_strats = index_strategies()
    n_trades = sync_live_trades_from_db()
    print(f"[RAG] Bootstrapped: {n_strats} strategies, {n_trades} live trades indexed.")


if __name__ == "__main__":
    bootstrap()
    ctx = query_full_context("EURUSD", "LONDON")
    print(ctx)
