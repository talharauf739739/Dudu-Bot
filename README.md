# ForgeX AI — Multi-Agent Trading System

> Version 1.0 | Mode: DEMO FIRST | Protocol: MCP | Status: Build  
> A fully autonomous multi-agent system that monitors markets, filters news, picks optimal strategies, enforces prop firm rules, executes trades on demo accounts, and journals every trade — all connected via MCP to real third-party services.

---

## System at a Glance

| Component | Count |
|-----------|-------|
| AI Agents | 8 |
| MCP Servers | 9 (3 connected + 6 custom) |
| Instruments | 11 |
| Strategies | 10 |
| Prop Firms | 6 |
| Build Phases | 4 |

---

## Architecture Overview

```
Layer 1 — Data (MCP Sources)
  News MCP (ForexFactory + NewsAPI)
  Market MCP (TradingView Webhooks)
  PropFirm MCP (Rules KB + Drawdown)
         ↓
Layer 2 — Agents (Decision Making)
  Orchestrator routes 8 agents | State manager
         ↓
Layer 3 — Execution (TradeLocker DEMO)
  DEMO execution via MCP | Prop firm rules enforced before every trade
         ↓
Layer 4 — Records (Google Drive + PostgreSQL)
  Every trade logged | Equity curve graphs | Daily Telegram summary
```

---

## Project Structure

```
Dudu-Bot/
├── app.py                          # FastAPI entry point (UI + API)
├── README.md
├── Methodology.md
├── requirements.txt
├── .env.example
│
├── agents/                         # 8 Autonomous AI Agents
│   ├── agent_01_news_sentinel.py   # News & economic calendar monitor
│   ├── agent_02_signal_hunter.py   # Market scanner & setup scorer
│   ├── agent_03_strategy_oracle.py # Strategy picker & entry calculator
│   ├── agent_04_risk_enforcer.py   # Prop firm rule checker (8 checks)
│   ├── agent_05_executor.py        # TradeLocker order execution
│   ├── agent_06_recorder.py        # Trade journal & Telegram alerts
│   ├── agent_07_forecaster.py      # Performance analysis & forecasting
│   └── agent_08_orchestrator.py    # LangGraph master controller
│
├── mcp_servers/                    # 6 Custom MCP Servers (Python MCP SDK)
│   ├── mcp_propfirm_kb/            # Prop firm rules database
│   ├── mcp_forexfactory/           # ForexFactory calendar scraper
│   ├── mcp_tradelocker/            # TradeLocker REST API bridge
│   ├── mcp_tradingview/            # TradingView webhook receiver
│   ├── mcp_telegram/               # Telegram Bot notifications
│   └── mcp_journal/                # PostgreSQL + Google Drive sync
│
├── knowledge_base/                 # Static knowledge stores
│   ├── strategies/                 # 10 strategy definitions (JSON)
│   └── prop_firms/                 # 6 prop firm rule sets (JSON)
│
├── database/                       # PostgreSQL schema & migrations
│   ├── schema.sql
│   └── migrations/
│
├── core/                           # Shared internals
│   ├── config.py                   # Environment & constants
│   ├── models.py                   # Pydantic data models
│   └── state.py                    # LangGraph global state
│
├── api/                            # FastAPI routers
│   ├── routes/
│   │   ├── dashboard.py            # Live system status
│   │   ├── trades.py               # Trade history & journal
│   │   ├── agents.py               # Agent status & logs
│   │   └── analytics.py            # Equity curves & win rates
│   └── schemas/
│       └── trade_schema.py         # Request/response schemas
│
└── tests/
    ├── test_agents/
    ├── test_mcp/
    └── test_api/
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Orchestration | Python + LangGraph | Agent coordination & state management |
| MCP Protocol | Anthropic MCP SDK (Python) | All 3rd party connections |
| LLM Brain | Claude claude-sonnet-4-20250514 | Agent reasoning & decisions |
| UI / API | FastAPI (`app.py`) | Dashboard & REST endpoints |
| Execution | TradeLocker REST API | DEMO trade placement |
| Chart Signals | TradingView Webhooks + Pine Script | Setup detection → MCP alerts |
| News Feed | ForexFactory + NewsAPI | Fundamental event filtering |
| Storage | PostgreSQL + Google Drive MCP | Trade journal & tabular records |
| Notifications | Telegram Bot API | Real-time trade alerts |
| Graphs | Plotly Python | Equity curve, win-rate charts |

---

## The 8 Agents

| Agent | Name | Role |
|-------|------|------|
| Agent-01 | News Sentinel | Monitors economic calendar 24/5, blocks trades during high-impact windows |
| Agent-02 | Signal Hunter | Scans all 11 instruments for setups, scores 1-10, passes only 7.5+ |
| Agent-03 | Strategy Oracle | Matches confirmed setups to best strategy, calculates Entry/SL/TP |
| Agent-04 | Risk Enforcer | Runs 8 prop firm rule checks — one fail = trade blocked |
| Agent-05 | Executor | Places and manages full trade lifecycle on TradeLocker DEMO |
| Agent-06 | Recorder | Logs every trade to PostgreSQL + Google Drive, sends Telegram summary |
| Agent-07 | Forecaster | Analyzes journal data, detects patterns, predicts next-session setups |
| Agent-08 | Orchestrator | Master controller — session timer, circuit breaker, final approval gate |

**Agent flow:** `01 → 02 → 03 → 04 → 05 → 06` (routed by Agent-08)

---

## Instruments Traded

**Tier 1** (Primary): EUR/USD, USD/JPY, GBP/USD, NAS100, US500  
**Tier 2** (Secondary): USD/CHF, AUD/USD, US30 (Dow), USD/CAD  
**Tier 3** (Selective): EUR/JPY, GBP/JPY  

---

## Prop Firms Supported

| Firm | Daily DD | Max DD | Payout | EA Bots | Min Hold |
|------|----------|--------|--------|---------|----------|
| FundedNext | 5% | 10% | 95% | Full | None |
| FXIFY | 5% | 10% | 100% | Full | None |
| FundingPips | 5% | Static | 95% | Partial | 60 sec |
| E8 Markets | Varies | 14% | 100% | Full | None |
| FTMO | 5% | 10% | 90% | Yes | None |
| The5ers | 5% | 8% | 100% | Full | None |

---

## Build Phases

| Phase | Timeline | Focus |
|-------|----------|-------|
| Phase 1 — Foundation | Week 1-2 | mcp-propfirm-kb, mcp-forexfactory, PostgreSQL, LangGraph Orchestrator |
| Phase 2 — Execution | Week 3-4 | mcp-tradelocker, mcp-tradingview, wire all 8 agents, Telegram + Forecaster |
| Phase 3 — Demo Live Testing | Month 2 | 4-week DEMO run, backtest & optimize, validate all prop firm rules |
| Phase 4 — Live Challenges | Month 3+ | FundedNext/FXIFY challenge, scale to all 6 firms, continuous improvement |

---

## Build Priority Order

| Order | Component | Est. Time |
|-------|-----------|-----------|
| 1st | mcp-propfirm-kb | 1 day |
| 2nd | mcp-forexfactory | 2 days |
| 3rd | PostgreSQL journal schema | 1 day |
| 4th | mcp-tradelocker (DEMO) | 3 days |
| 5th | mcp-tradingview (webhook) | 3 days |
| 6th | LangGraph Orchestrator | 4 days |

---

## Quick Start (Coming in Phase 1)

```bash
git clone <repo>
cd Dudu-Bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Fill in API keys
uvicorn app:app --reload      # Start FastAPI dashboard
```

---

## Sessions

- **London Open:** 08:00 – 12:00 GMT
- **NY Session:** 13:30 – 17:00 GMT  
- **System Sleep:** Outside these windows

> DEMO MODE ONLY — All prop firm rules enforced even on demo to build live discipline.
