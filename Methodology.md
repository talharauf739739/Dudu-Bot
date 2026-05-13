# ForgeX AI — Methodology & Tool Framework

> AGI-Based Autonomous Trading System | Blueprint v1.0 | May 2026  
> This document defines every framework, tool, protocol, and design decision used to build ForgeX AI.

---

## Table of Contents

1. [System Philosophy](#1-system-philosophy)
2. [Architecture Layers](#2-architecture-layers)
3. [Orchestration Framework — LangGraph](#3-orchestration-framework--langgraph)
4. [LLM Brain — Claude API](#4-llm-brain--claude-api)
5. [MCP Protocol — Anthropic MCP SDK](#5-mcp-protocol--anthropic-mcp-sdk)
6. [The 8 Agents — Detailed Spec](#6-the-8-agents--detailed-spec)
7. [MCP Servers — All 9 Defined](#7-mcp-servers--all-9-defined)
8. [Strategy Knowledge Base](#8-strategy-knowledge-base)
9. [Prop Firm Rules Engine](#9-prop-firm-rules-engine)
10. [Trade Execution Pipeline](#10-trade-execution-pipeline)
11. [Trade Journal & Storage Schema](#11-trade-journal--storage-schema)
12. [Notification System — Telegram](#12-notification-system--telegram)
13. [Analytics & Visualization — Plotly](#13-analytics--visualization--plotly)
14. [UI Layer — FastAPI](#14-ui-layer--fastapi)
15. [Build Plan — 4 Phases](#15-build-plan--4-phases)

---

## 1. System Philosophy

ForgeX AI is built on a **demo-first, rules-first** principle:

- **Demo First:** All execution happens on TradeLocker DEMO accounts. No live money until Phase 4, and only after 65%+ win rate is sustained over 4 weeks.
- **Rules First:** Every trade must pass 8 prop firm compliance checks before any order is placed. One failure = blocked, always.
- **MCP Integrated:** All third-party connections (ForexFactory, TradingView, TradeLocker, Telegram, Google Drive) go through the Model Context Protocol, making them swappable, auditable, and agent-accessible.
- **AI Decision Engine:** Claude reasons over data. Agents don't hardcode signals — they reason, score, and decide. This is what separates AGI-based trading from a simple indicator bot.

---

## 2. Architecture Layers

The system is designed as four discrete layers, each with a clear contract to the next.

### Layer 1 — Data (MCP Sources)

All external data enters the system via MCP servers. Agents never call external APIs directly.

| Source | MCP Server | Data Provided |
|--------|-----------|---------------|
| ForexFactory.com | `mcp-forexfactory` | Economic calendar events, impact scores |
| NewsAPI.org | `mcp-forexfactory` | Breaking macro news, sentiment |
| TradingView | `mcp-tradingview` | Webhook alerts, Pine Script signals, setup scores |
| TradeLocker | `mcp-tradelocker` | Market data, open positions, account balance |
| Google Drive | (pre-connected) | Trade journal spreadsheet sync |
| Gmail | (pre-connected) | Prop firm challenge notifications |
| Google Calendar | (pre-connected) | Session scheduling |

### Layer 2 — Agents (Decision Making)

8 specialized AI agents, each with a single responsibility. They communicate via shared LangGraph state. No agent calls another directly — all routing goes through Agent-08 (Orchestrator).

### Layer 3 — Execution (TradeLocker DEMO)

All orders placed through `mcp-tradelocker`. Prop firm rules are enforced by Agent-04 before Agent-05 ever fires. The Executor monitors position health every 30 seconds.

### Layer 4 — Records (PostgreSQL + Google Drive)

Every trade decision — win, loss, or blocked — is logged. Agent-06 saves to PostgreSQL and syncs to Google Drive. Agent-07 reads this data to continuously improve strategy selection.

---

## 3. Orchestration Framework — LangGraph

**Library:** `langgraph` (Python)  
**Pattern:** StateGraph with typed nodes, conditional edges, circuit breaker

LangGraph is chosen over CrewAI for its explicit state machine model. Every decision point is a node; every routing condition is an edge. This makes the system debuggable, restartable, and auditable.

### Global State Schema

```python
class ForgeXState(TypedDict):
    session_active: bool
    news_status: dict          # {currency: NEWS_SAFE | NEWS_BLOCK}
    active_signals: list       # Scored setups from Agent-02
    selected_trade: dict       # Chosen trade from Agent-03
    risk_verdict: str          # APPROVED | BLOCKED + reason
    order_result: dict         # TradeLocker order response
    daily_dd_pct: float        # Consumed daily drawdown
    circuit_breaker: bool      # True = system paused
```

### Agent Routing Flow

```
Agent-08 checks session
    → Agent-01 (news check)
        → Agent-02 (scan signals)
            → Agent-03 (pick strategy)
                → Agent-04 (risk check)
                    → [APPROVED] → Agent-05 (execute)
                                       → Agent-06 (record)
                    → [BLOCKED]  → Agent-06 (log block, no trade)
    → Agent-07 (end of session, analyze + forecast)
```

### Circuit Breaker

Agent-08 monitors `daily_dd_pct` continuously. At 80% of the firm's daily DD limit, the system pauses all new trades for the remainder of the session. This protects against cascading losses.

### Session Timer

- **Start:** London open — 08:00 GMT
- **Stop:** NY close — 21:00 GMT
- **Outside hours:** System sleeps, no agents active

---

## 4. LLM Brain — Claude API

**Model:** `claude-sonnet-4-20250514`  
**SDK:** `anthropic` Python SDK  
**Used by:** Agent-03 (Strategy Oracle), Agent-07 (Forecaster)

Claude is used for reasoning tasks that cannot be reduced to deterministic logic:

- **Agent-03:** Given an instrument, session, and detected pattern — reason over the strategy knowledge base to select the highest-probability strategy. Calculate precise Entry, SL, and TP levels. Reject if expected win rate is below 65%.
- **Agent-07:** Given 30 days of trade journal data — identify performance patterns by hour, session, strategy, and instrument. Output probability scores and "best setup tomorrow" brief.

All other agents (01, 02, 04, 05, 06, 08) use deterministic logic + MCP tool calls. Claude is reserved for genuine reasoning, not rule execution.

**Key API Settings:**
- Temperature: 0.1 (near-deterministic for trading decisions)
- Max tokens: 1024 per agent call
- System prompt: injects current strategy KB and prop firm rules as context

---

## 5. MCP Protocol — Anthropic MCP SDK

**SDK:** `mcp` Python SDK (Anthropic)  
**Pattern:** Each MCP server is a standalone Python process exposing typed tools to agents

The Model Context Protocol is the backbone of ForgeX AI. Every external integration is wrapped in an MCP server. This provides:

- **Isolation:** Agents can't accidentally call APIs in unintended ways
- **Composability:** Any agent can call any MCP tool with a single line
- **Auditability:** All MCP calls are logged with inputs/outputs
- **Replaceability:** Swap TradeLocker for another broker by rebuilding one MCP server

**MCP Call Pattern:**

```python
result = await mcp_client.call_tool(
    "mcp-tradelocker",
    "place_order",
    {"symbol": "EURUSD", "dir": "BUY", "size": 0.08, "sl": 1.0878, "tp": 1.0920}
)
```

---

## 6. The 8 Agents — Detailed Spec

### Agent-01 — News Sentinel
**Type:** News & Fundamentals  
**Trigger:** Every 5 minutes during session hours  
**MCP Tools:** `mcp-forexfactory`, `mcp-newsapi`

**Responsibilities:**
- Calls `mcp-forexfactory.get_events_today()` — returns list of `{time, currency, impact}`
- Scores events: HIGH / MEDIUM / LOW impact
- Blocks all USD pairs 30min before/after NFP, CPI, FOMC
- Calls `mcp-newsapi` for breaking macro news
- Publishes `NEWS_SAFE` or `NEWS_BLOCK(currency, event, time)` to global state

**Output:** `NEWS_SAFE` | `NEWS_BLOCK(currency, event, time)`

---

### Agent-02 — Signal Hunter
**Type:** Market Scanner  
**Trigger:** On TradingView webhook alert (real-time)  
**MCP Tools:** `mcp-tradingview`, `mcp-tradelocker`

**Responsibilities:**
- Receives TradingView webhook alerts for all 11 instruments
- Detects: Order Blocks, FVGs, BOS, ChoCH, VWAP levels
- Confirms session context: London open or NY open only
- Scores setup quality 1–10 based on spread, momentum, structure alignment
- Filters out spreads above threshold
- Only passes setups scoring **7.5 or above** to Agent-03

**Output:** `Setup{symbol, tf, pattern, score, entry_zone}` | Discarded if score < 7.5

---

### Agent-03 — Strategy Oracle
**Type:** Strategy Picker  
**Trigger:** On confirmed setup from Agent-02  
**MCP Tools:** `mcp-propfirm-kb`; **LLM:** Claude API

**Responsibilities:**
- Loads strategy KB from `mcp-propfirm-kb`
- Matches `instrument + session + detected pattern` → best strategy ID
- Retrieves historical win rate for that strategy on that instrument
- Uses Claude to calculate precise Entry, SL, and TP based on strategy rules
- Sets R:R ratio — minimum 1:2, prefers 1:3
- **Rejects trade** if expected win rate for that setup is below 65%

**Output:** `Trade{symbol, dir, entry, sl, tp, strategy_id, rr}` | Rejected if win rate < 65%

---

### Agent-04 — Risk Enforcer
**Type:** Risk Guard  
**Trigger:** On every trade candidate from Agent-03  
**MCP Tools:** `mcp-propfirm-kb`

**8 Mandatory Checks — ALL must pass:**

| # | Check | Threshold |
|---|-------|-----------|
| 1 | Session active? | London / NY only |
| 2 | News window clear? | From Agent-01 output |
| 3 | Daily loss < limit? | Per firm (typically 5%) |
| 4 | Total DD < max? | Per firm (typically 10%) |
| 5 | Position size ≤ 1%? | Account risk |
| 6 | Consistency OK? | No single day > 35% of total profit |
| 7 | Hold time will exceed 60s? | FundingPips rule |
| 8 | Win rate ≥ 65%? | From journal stats (Agent-07 output) |

**Output:** `APPROVED` | `BLOCKED(reason)` — reason is always logged

---

### Agent-05 — Executor
**Type:** Trade Executor  
**Trigger:** Only after Agent-04 returns APPROVED  
**MCP Tools:** `mcp-tradelocker` (DEMO only)

**Responsibilities:**
- Calls `mcp-tradelocker.place_order(symbol, dir, size, sl, tp)`
- Monitors open position every **30 seconds**
- **Partial close:** 50% of position at 1:1 R:R to lock profit
- **Breakeven move:** Moves SL to entry after 1:1 hit
- Closes position when TP or SL is hit
- Reports full result to Agent-06 immediately after close

**Output:** `OrderResult{id, filled_price, status}` → passed to Agent-06

---

### Agent-06 — Recorder
**Type:** Journal Agent  
**Trigger:** After every trade (win, loss, or blocked)  
**MCP Tools:** `mcp-journal`, `mcp-gdrive`, `mcp-telegram`

**Responsibilities:**
- Saves all trade fields to PostgreSQL via `mcp-journal.log_trade()`
- Calls `mcp-gdrive` to update Google Sheet with trade row
- Updates daily P&L vs prop firm limit per account
- Generates equity curve graph via Plotly
- Calculates win rate per strategy per session
- Sends Telegram summary at end of session

**Output:** Trade ID saved to DB, Google Sheet updated, Telegram sent

---

### Agent-07 — Forecaster
**Type:** Performance Analyst  
**Trigger:** End of each trading session  
**MCP Tools:** `mcp-journal`; **LLM:** Claude API

**Responsibilities:**
- Reads all trade records from journal MCP
- Calculates win rate by: hour, day, session, strategy, instrument
- **Flags** strategies with win rate drop below 60%
- Identifies best-performing instrument × timeframe combinations
- Uses Claude to reason over patterns and generate probabilistic forecast
- Sends daily Telegram brief: "Best setup tomorrow: X"
- Outputs probability score per setup pattern → updates Agent-04 check #8

**Output:** Performance report + probability scores + Telegram forecast brief

---

### Agent-08 — Orchestrator
**Type:** Master Controller  
**Framework:** LangGraph StateGraph  
**Always running during session hours**

**Responsibilities:**
- Starts all agents at London open (08:00 GMT)
- Stops all agents at NY close (21:00 GMT)
- Routes: `Agent-01 → 02 → 03 → 04 → 05 → 06`
- Manages priority queue for multiple simultaneous signals
- Circuit breaker: pauses system at 80% of daily DD limit
- Restarts failed agents automatically (with retry limit)
- Single approval gate before Agent-05 executes (final human override hook point)

---

## 7. MCP Servers — All 9 Defined

### Pre-Connected (Claude Workspace)

| Server | Purpose |
|--------|---------|
| Google Drive MCP | Trade journal spreadsheet — auto-sync |
| Gmail MCP | Prop firm challenge alerts |
| Google Calendar MCP | Session scheduling |

### Custom MCP Servers to Build (Priority Order)

---

#### mcp-propfirm-kb (Build 1st)
**Backend:** Local JSON + PostgreSQL  
**Purpose:** Prop Firm Rules Database — Agent-04's source of truth

```
get_firm_rules(firm_name)              → FirmRules object
check_drawdown_ok(firm, current_dd, type) → bool + remaining%
is_trade_allowed(firm, params)         → APPROVED | BLOCKED + reason
get_daily_remaining(firm, account_id)  → float
check_consistency(firm, day_profit, total) → bool
```

---

#### mcp-forexfactory (Build 2nd)
**Backend:** ForexFactory.com scraper + NewsAPI.org  
**Purpose:** Economic calendar and macro news filter

```
get_events_today()                     → List[Event{time, currency, impact}]
is_news_window(currency, buffer_min=30) → bool
get_next_high_impact(currency)         → Event | None
get_live_news(keywords)                → List[Article]
score_sentiment(currency)              → BULLISH | BEARISH | NEUTRAL
```

---

#### mcp-tradelocker (Build 3rd)
**Backend:** TradeLocker REST API — DEMO accounts only  
**Purpose:** Order placement and position management

```
place_order(symbol, dir, size, sl, tp)     → OrderResult
get_open_positions(account_id)             → List[Position]
close_position(order_id, partial_size?)    → CloseResult
modify_sl_tp(order_id, new_sl, new_tp)    → bool
get_account_balance(account_id)            → BalanceSummary
get_daily_pnl(account_id)                 → float
```

---

#### mcp-tradingview (Build 4th)
**Backend:** TradingView Webhook receiver + Pine Script alerts  
**Purpose:** Chart signal ingestion for Agent-02

```
subscribe_alerts(symbols: List[str])       → WebhookEndpoint
get_latest_alert(symbol)                   → Alert{strategy, signal, score}
check_ema_cross(symbol, tf, fast, slow)    → CROSS_UP | CROSS_DOWN | NONE
detect_order_block(symbol, tf)             → List[OrderBlock]
get_vwap(symbol)                           → float
```

---

#### mcp-telegram (Build 5th)
**Backend:** Telegram Bot API  
**Purpose:** Real-time notifications to phone

```
send_trade_opened(trade: TradeRecord)      → bool
send_trade_closed(trade, result, pnl)      → bool
send_daily_summary(summary: DailySummary)  → bool
send_news_block(event, currency)           → bool
send_graph(image_path, caption)            → bool
```

---

#### mcp-journal (Build 6th)
**Backend:** PostgreSQL (local) + Google Drive MCP sync  
**Purpose:** Persistent trade logging and analytics

```
log_trade(trade: TradeRecord)              → trade_id
update_trade_result(trade_id, result, pnl) → bool
get_strategy_stats(strategy_id, days=30)   → Stats
export_to_sheet(sheet_id, date_range)      → bool
generate_equity_graph(account_id)          → image_path
```

---

## 8. Strategy Knowledge Base

10 strategies, each with defined instruments, timeframe, win rate target, R:R, and session.

| ID | Strategy | Instruments | TF | Win Rate | R:R | Session |
|----|----------|------------|-----|----------|-----|---------|
| S-01 | ICT Order Block + FVG | EUR/USD, NAS100, US30 | 5min | 70-75% | 1:3-1:5 | London / NY |
| S-02 | EMA 5/20 + RSI Filter | EUR/USD, GBP/USD, USD/JPY, AUD/USD | 1m/5m | 70-75% | 1:2 | London-NY Overlap |
| S-03 | SMC — BOS + ChoCH | All 11 instruments | 5min | 60-70% | 1:2-1:3 | London / NY |
| S-04 | VWAP Rejection Scalp | NAS100, US30, US500, GBP/JPY | 1m/5m | 68-72% | 1:2 | NY Open (1st hr) |
| S-05 | London Breakout | EUR/USD, GBP/USD, USD/CHF, EUR/JPY | 5min | 70-75% | 1:2 | 07:00-08:00 GMT |
| S-06 | NAS100-US30 Correlation | NAS100 + US30 together | 1min | 65-70% | 1:2 | NY Session |
| S-07 | Keltner Channel + RSI | EUR/USD, NAS100, GBP/JPY, USD/JPY | 1m/5m | 68-72% | 1:2 | London / NY |
| S-08 | ICT Killzone — NY Open | EUR/USD, GBP/USD, NAS100, US30 | 5min | 65-75% | 1:3 | 13:30-15:00 GMT |
| S-09 | MACD + RSI Momentum | USD/CHF, AUD/USD, EUR/JPY, US500 | 5min | 65-70% | 1:2 | London / NY |
| S-10 | Heikin-Ashi Pullback | EUR/USD, GBP/USD, NAS100 | 5min | 68-72% | 1:2 | London / NY |

### Instrument × Strategy Lookup (Agent-03 Matrix)

| Instrument | 1min Best Strategy | 5min Best Strategy | Avg Win Rate | Target Profit |
|-----------|-------------------|-------------------|-------------|--------------|
| EUR/USD | S-02 EMA 5/20 + RSI | S-01 ICT OB + FVG | 70-75% | 8-12 pips |
| GBP/USD | S-02 EMA 5/20 + RSI | S-05 London Breakout | 70-74% | 10-15 pips |
| USD/JPY | S-07 Keltner + RSI | S-03 SMC BOS | 65-70% | 8-12 pips |
| NAS100 | S-04 VWAP Rejection | S-08 ICT Killzone | 70-75% | 15-25 pts |
| US500 | S-04 VWAP Rejection | S-01 ICT OB | 68-73% | 5-10 pts |
| US30 | S-06 Correlation | S-04 VWAP Rejection | 65-70% | 20-35 pts |
| AUD/USD | S-02 EMA Cross | S-09 MACD + RSI | 65-70% | 7-10 pips |
| EUR/JPY | S-07 Keltner | S-05 London Breakout | 65-68% | 10-15 pips |

---

## 9. Prop Firm Rules Engine

Agent-04 enforces rules per firm, per account. All rules stored in `mcp-propfirm-kb`.

### Firm Rule Summary

| Firm | P1 Target | P2 Target | Daily DD | Max DD | Payout | EA Bots | Min Hold |
|------|-----------|-----------|----------|--------|--------|---------|----------|
| FundedNext | 8% | 5% | 5% | 10% | 95% | Full | None |
| FXIFY | 8% | 5% | 5% | 10% | 100% | Full | None |
| FundingPips | 10% | 8%/5% | 5% | Static | 95% | Partial (SL/TP only) | 60 sec |
| E8 Markets | 6% | 8%/4% | Varies | 14% | 100% | Full | None |
| FTMO | 10% | 5% | 5% | 10% | 90% | Yes | None |
| The5ers | 5-10% | — | 5% | 8% | 100% | Full | None |

### Universally Banned Across All Firms

- HFT / Latency arbitrage
- Tick scalping (sub-second execution)
- Grid / Martingale strategies
- Coordinated copy networks (multi-account)
- Opposite account / hedge arbitrage
- Server spamming / price gap trading
- Instant open/close (0-second hold)

### Agent-04 Check Order (Every Trade)

```
1. Session active?         London / NY only
2. News window clear?      From Agent-01
3. Daily loss < limit?     Per firm (5%)
4. Total DD < max?         Per firm (10%)
5. Position size ≤ 1%?     Account risk
6. Consistency OK?         No single day > 35% of total profit
7. Hold time > 60s?        FundingPips rule (enforced for all)
8. Win rate ≥ 65%?         From Agent-07 journal stats

ALL 8 PASS → APPROVED
ANY SINGLE FAIL → BLOCKED (reason logged)
```

---

## 10. Trade Execution Pipeline

Step-by-step flow for every signal from detection to journal entry.

```
Step 1  ORCHESTRATOR — Is London or NY session active?
        → SESSION_ACTIVE or SLEEP

Step 2  AGENT-01 — Pull calendar. Red events in next 30min?
        → NEWS_SAFE or NEWS_BLOCK(currency, event, time)

Step 3  AGENT-02 — Scan all 11 instruments for high-score setups
        → Setup{symbol, tf, pattern, score ≥ 7.5, entry_zone}

Step 4  AGENT-03 — Match setup → best strategy → calculate Entry/SL/TP
        → Trade{symbol, dir, entry, sl, tp, strategy_id, rr}

Step 5  AGENT-04 — Run all 8 prop firm rule checks
        → APPROVED or BLOCKED(reason)

Step 6  AGENT-05 — Place order on TradeLocker DEMO
        → OrderResult{id, filled_price, status}

Step 7  AGENT-06 — Log full record to PostgreSQL + Google Drive
        → trade_id saved, sheet updated, Telegram alert sent

Step 8  AGENT-07 (End of session) — Analyze + update model + send forecast
        → Telegram daily brief sent
```

---

## 11. Trade Journal & Storage Schema

### PostgreSQL Table: `trades`

```sql
CREATE TABLE trades (
    trade_id      SERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ,
    instrument    VARCHAR(12),       -- EURUSD
    direction     VARCHAR(4),        -- BUY | SELL
    strategy_id   VARCHAR(6),        -- S-01
    timeframe     VARCHAR(4),        -- 1min | 5min
    session       VARCHAR(10),       -- LONDON | NY
    entry_price   DECIMAL(12,5),
    sl_price      DECIMAL(12,5),
    tp_price      DECIMAL(12,5),
    risk_rr       DECIMAL(4,2),      -- 2.0 / 3.0
    lot_size      DECIMAL(6,3),
    result        VARCHAR(4),        -- WIN | LOSS | BE
    close_price   DECIMAL(12,5),
    pnl_usd       DECIMAL(10,2),
    hold_time_s   INTEGER,           -- seconds
    prop_firm     VARCHAR(20),
    account_id    VARCHAR(20),
    daily_dd_pct  DECIMAL(5,2),
    notes         TEXT
);
```

### Google Sheet Columns (Auto-synced via MCP)

| Column | Example |
|--------|---------|
| Trade ID | #T-001 |
| Date & Time (GMT) | 2025-05-06 08:14 |
| Instrument | EUR/USD |
| Direction | BUY |
| Strategy | S-01 ICT OB+FVG |
| Timeframe | 5min |
| Session | London |
| Entry Price | 1.08920 |
| Stop Loss | 1.08780 |
| Take Profit | 1.09200 |
| R:R Ratio | 1:2.0 |
| Lot Size | 0.08 |
| Result | WIN |
| P&L ($) | +$84.00 |
| Hold Time | 17 min |
| Prop Firm | FundedNext |
| Daily DD Used | 1.5% |
| Rule Checks | ALL PASS |

---

## 12. Notification System — Telegram

**Framework:** Telegram Bot API  
**MCP Server:** `mcp-telegram`

Daily Telegram summary format sent by Agent-06 at session close:

```
FORGEX DAILY BRIEF — 2025-05-06
Session: London + NY | Duration: 6h 32min

PERFORMANCE
Trades: 7 | Wins: 5 | Losses: 2
Win Rate: 71.4% | Avg R:R: 1:2.2
Net P&L: +$284.00

PROP FIRM DRAWDOWN TRACKER
FundedNext | Daily: 0.0% used | Total: 1.8%
FXIFY      | Daily: 0.0% used | Total: 0.9%
FundingPips| Daily: 0.0% used | Total: 2.1%

BEST STRATEGY TODAY
S-01 ICT OB+FVG: 3/3 wins (100%)
S-05 London Breakout: 2/3 wins (67%)

TOMORROW FORECAST (Agent-07)
Best window: London open 08:00 GMT
Top setup: EURUSD 5min — S-01 ICT OB
Watch: USD CPI at 12:30 GMT
```

---

## 13. Analytics & Visualization — Plotly

**Framework:** `plotly` Python  
**Generated by:** Agent-06 (Recorder)  
**Stored in:** PostgreSQL + Google Drive  
**Sent via:** `mcp-telegram.send_graph()`

Charts generated per account:
- Equity curve (cumulative P&L over time)
- Win rate by strategy (bar chart)
- Win rate by session (London vs NY)
- Daily drawdown tracker per prop firm
- R:R distribution histogram

---

## 14. UI Layer — FastAPI

**Framework:** `fastapi` + `uvicorn`  
**Entry point:** `app.py`  
**Purpose:** Dashboard for monitoring system state, viewing trade journal, and controlling agents

### Planned Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Dashboard — live system status |
| `/agents/status` | GET | All 8 agent states + last action |
| `/trades` | GET | Full trade journal with filters |
| `/trades/{id}` | GET | Single trade detail |
| `/analytics/equity` | GET | Equity curve data (JSON) |
| `/analytics/winrate` | GET | Win rate by strategy/session |
| `/drawdown` | GET | Live DD tracker per prop firm |
| `/signals` | GET | Active setups from Agent-02 |
| `/system/start` | POST | Start Orchestrator (manual override) |
| `/system/stop` | POST | Stop all agents |
| `/system/state` | GET | Full LangGraph state dump |

FastAPI is chosen for:
- Speed (async native)
- Auto-generated `/docs` (Swagger UI) — inspect all endpoints with zero frontend work
- Easy Pydantic model integration (same models used by agents)
- Simple deployment (single `uvicorn app:app` command)

---

## 15. Build Plan — 4 Phases

### Phase 1 — Foundation (Week 1-2)

| Step | Task | Est. Time |
|------|------|-----------|
| 1 | Build `mcp-propfirm-kb` — JSON rules for all 6 firms, Agent-04 validation | 1 day |
| 2 | Build `mcp-forexfactory` — ForexFactory scraper + news impact scorer | 2 days |
| 3 | Setup PostgreSQL + Google Drive sync — trade schema, `log_trade()`, `export_to_sheet()` | 1 day |
| 4 | Build Orchestrator (LangGraph) — state graph, session timer, agent routing, circuit breaker | 2 days |

**Deliverable:** System can evaluate news, check prop firm rules, and manage agent routing — without live trades.

### Phase 2 — Execution (Week 3-4)

| Step | Task | Est. Time |
|------|------|-----------|
| 5 | Build `mcp-tradelocker` — connect REST API, test `place_order`, `get_positions`, `close_position` | 3 days |
| 6 | Build `mcp-tradingview` — webhook receiver, Pine Script alerts for S-01 to S-05 | 3 days |
| 7 | Wire all 8 agents together — full pipeline, run on paper 1 week, log every decision | 3 days |
| 8 | Build `mcp-telegram` + Agent-07 Forecaster — daily briefs, equity graphs, win-rate analysis | 2 days |

**Deliverable:** Full autonomous pipeline running. Every decision logged even when no trade is placed.

### Phase 3 — Demo Live Testing (Month 2)

| Step | Task |
|------|------|
| 9 | Run full system on DEMO for 4 weeks across all 6 prop firm accounts simultaneously |
| 10 | Backtest & optimize strategies — remove any strategy below 62% win rate |
| 11 | Validate all prop firm rule enforcement — simulate full P1→P2 challenge progression |

**Target:** 65%+ sustained win rate before moving to Phase 4.

### Phase 4 — Live Challenges (Month 3+)

| Step | Task |
|------|------|
| 12 | Start with cheapest prop firm challenge — FundedNext ($32.99) or FXIFY ($39) |
| 13 | Scale to multiple firms after passing — add E8, FTMO, The5ers. Agent-04 manages each firm separately |
| 14 | Continuous improvement loop — Agent-07 keeps optimizing. New strategies added to KB. Win rates auto-adjusted |

---

## Priority Build Order Summary

| Order | Component | Why First | Est. Time |
|-------|-----------|-----------|-----------|
| 1st | `mcp-propfirm-kb` | Risk Guard needs this before any trade can be evaluated | 1 day |
| 2nd | `mcp-forexfactory` | Without news filtering, USD trades are dangerous | 2 days |
| 3rd | PostgreSQL journal schema | Without records, no learning or tracking possible | 1 day |
| 4th | `mcp-tradelocker` (DEMO) | Core execution — test order placement on safe demo | 3 days |
| 5th | `mcp-tradingview` (webhook) | Signal source — needs Pine Script + webhook server | 3 days |
| 6th | LangGraph Orchestrator | Ties everything together — build after all MCPs confirmed | 4 days |

---

> ForgeX AI — Demo First. Rules First. AGI Powered.  
> Version 1.0 | May 2026 | 8 Agents · 9 MCPs · 6 Prop Firms
