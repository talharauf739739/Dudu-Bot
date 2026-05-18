# ForgeX AI — Simple Methodology

## Think of it as a Trading Company

---

## The Building (Your Computer)

Two offices are always open:

| Office | Address | What it does |
|--------|----------|--------------|
| **Streamlit UI** | `localhost:8501` | The front desk — what you see and click |
| **FastAPI Engine** | `localhost:8000` | The engine room — does all the real work |

Both must be running at the same time. If FastAPI is off, the Live Dashboard shows "Connection refused."

---

## The Front Desk (Streamlit UI)

Has 3 rooms you can walk into:

1. **Backtest Room** — Test a strategy on old price data. Did it work in the past?
2. **Prop Sim Room** — Simulate trading under prop firm rules (FundedNext, FTMO, etc.) without real money.
3. **Live Dashboard** — Watch the bot trade in real-time. Shows open trades, P&L, signals.

---

## The 8 Employees (Agents)

When a trade signal arrives, it passes through 8 employees in order. Each one does one job and passes to the next.

```
Signal In
   │
   ▼
[Agent-01] News Filter      — Is there high-impact news right now? If yes, BLOCK.
   │
   ▼
[Agent-02] Signal Screener  — Score the setup out of 10. Below 7.5? REJECT.
   │
   ▼
[Agent-03] Strategy Oracle  — Ask Groq AI: which of our 10 strategies fits best?
   │
   ▼
[Agent-04] Risk Guardian    — Check: lot size, drawdown limit, prop firm rules. OK?
   │
   ▼
[Agent-05] Trade Executor   — Send the actual order to the broker (TradeLocker).
   │
   ▼
[Agent-06] Journal Keeper   — Save the trade to the SQLite database (forgex.db).
   │
   ▼
[Agent-07] Forecaster       — Ask Groq AI: predict outcome. Send Telegram alert.
   │
   ▼
[Agent-08] Orchestrator     — Coordinates all the above. The manager.
```

---

## The Brain (Groq AI)

- Only **Agent-03** and **Agent-07** use AI.
- We use **3 API keys × 3 models = 9 rotation slots** (all free, no card needed).
- If one key hits its rate limit, it automatically switches to the next slot.

**Models used (fastest → most powerful):**
1. `llama-3.1-8b-instant` — fast, high daily limit
2. `gemma2-9b-it` — medium speed
3. `llama-3.3-70b-versatile` — most capable

---

## The Filing Cabinet (SQLite Database)

- File location: `data/forgex.db`
- Stores every trade, every agent log, every drawdown snapshot.
- Zero setup — it's just a file on your computer.
- View it in VS Code: install **SQLite Viewer** (by Florian Klampfer) → click `data/forgex.db`.

**Tables:**
| Table | What's stored |
|-------|---------------|
| `trades` | Every trade: entry, SL, TP, result, P&L |
| `agent_logs` | Every decision each agent made |
| `drawdown_tracker` | Account balance snapshots |
| `signals` | Every signal that came in (passed or rejected) |

---

## The Toolbox (MCP Servers)

9 specialized tool servers the agents call for specific tasks:

| MCP Server | Job |
|------------|-----|
| `mcp-journal` | Read/write to the SQLite database |
| `mcp-tradelocker` | Connect to TradeLocker broker |
| `mcp-tradingview` | Receive signals from TradingView webhooks |
| `mcp-news` | Fetch ForexFactory / NewsAPI events |
| `mcp-risk` | Calculate lot sizes and risk levels |
| `mcp-backtest` | Run strategy backtests on historical data |
| `mcp-telegram` | Send alerts to your Telegram |
| `mcp-google-drive` | Export trades to Google Sheets |
| `mcp-prop-rules` | Enforce prop firm rules (FTMO, FundedNext, etc.) |

---

## What's Working Right Now

| Component | Status |
|-----------|--------|
| Streamlit UI (3 rooms) | Working |
| FastAPI engine | Working (`localhost:8000/health`) |
| SQLite database | Working (`data/forgex.db`) |
| Groq AI (3-key rotation) | Working |
| Backtest engine | Working |
| Prop Firm Simulator | Working |
| News filter | Working |
| Signal screener | Working |

---

## What Still Needs Setup

| What | Why it's blocked |
|------|-----------------|
| **Live trading** | TradeLocker email/password not filled in `.env` |
| **Telegram alerts** | Bot token + chat ID not filled in `.env` |
| **S-06 Strategy** | NAS100-US30 correlation signal — not coded yet |
| **S-08 Strategy** | ICT Killzone signal — not coded yet |

---

## The Flow in One Sentence

> TradingView sends a webhook → FastAPI receives it → 8 agents check it → if approved, broker executes the trade → SQLite saves it → Telegram notifies you.
