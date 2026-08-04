# Dudu-Bot — Top-Notch AI Trading Bot

## Vision

Build an AI-powered trading bot that outperforms the market by combining ML signal generation, fine-tuned expert knowledge, reinforcement learning position management, and a continuous self-learning loop. Supports both **Prop Firm** and **Personal** trading modes.

---

## Core Architecture

```
MARKET DATA
  └── Multi-TF OHLC (1m 5m 15m 1h 4h 1D) via yfinance + Deriv WebSocket
  └── News Feed (ForexFactory + NewsAPI)
  └── Sentiment Feed (TradingView public ideas)
         │
         ▼
REGIME DETECTOR  ──────────────────── AVOID if: news event / low liquidity
  └── XGBoost classifier               / high volatility / off-session
  └── Output: TRENDING | RANGING | VOLATILE | AVOID
         │
         ▼
SIGNAL ENGINE (Ensemble — all 3 must agree)
  ├── LSTM        → multi-timeframe price sequence patterns
  ├── XGBoost     → technical feature scoring (RSI, ATR, EMA, volume)
  └── CNN         → visual chart pattern detection (ICT/SMC setups)
         │
    Score 0–100
    Pass if ≥ 70
         │
         ▼
STRATEGY BRAIN
  ├── Fine-tuned Llama 3.1 8B  → trained on expert trader decisions
  └── RAG layer                → live news + session + recent trade context
  Output: Direction | Entry | SL | TP | Strategy ID
         │
         ▼
TRADING MODE SELECTOR
  ├── PROP FIRM MODE
  │     ├── Broker: TradeLocker (FundedNext, FTMO, FXIFY...)
  │     ├── Rules: Daily DD limit, Max DD limit, lot restrictions
  │     ├── Risk: Firm-defined (1% per trade, 5% daily max)
  │     └── Goal: Pass challenge → get funded
  │
  └── PERSONAL MODE
        ├── Broker: Deriv (demo or real)
        ├── Rules: None from firm — personal risk params only
        ├── Risk: Self-defined (flexible)
        └── Goal: Grow personal account freely
         │
         ▼
RISK GUARDIAN
  ├── Prop firm rules (daily DD, max DD, lot limits) — propfirm mode only
  ├── Personal risk params (risk %, daily loss limit) — personal mode only
  ├── Kelly Criterion position sizing
  ├── Correlation check (no 2 correlated pairs open)
  └── Session filter (London / NY only)
         │
         ▼
EXECUTION
  └── Deriv (personal mode) / TradeLocker (prop firm mode)
         │
         ▼
RL POSITION MANAGER (PPO Agent)
  ├── Monitors open trade every 30s
  ├── Decides: Hold | Partial Close | Move SL to BE | Full Exit
  └── Trained on historical simulations, improves from live trades
         │
         ▼
SELF-LEARNING LOOP
  ├── Every closed trade → SQLite + RAG indexed
  ├── XGBoost retrained on new labeled data
  ├── Llama fine-tuned periodically on accumulated decisions
  └── RL agent continues learning from live environment
```

---

## Trading Modes

### Prop Firm Mode
| Field | Value |
|-------|-------|
| Broker | TradeLocker |
| Firms Supported | FundedNext, FTMO, FXIFY, FundingPips, E8Markets, The5ers |
| Risk Rule Source | Prop firm (daily DD, max DD, lot limits per stage) |
| Goal | Pass challenge, get funded, scale |

### Personal Mode
| Field | Value |
|-------|-------|
| Broker | Deriv (demo: VRTC6144147 / real: CR3988560) |
| Risk Rule Source | Self-defined in `.env` |
| Goal | Grow personal capital freely |

Both modes share the same signal engine, strategy brain, and RL manager. Only risk layer and broker differ.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| API Framework | FastAPI |
| UI | Streamlit |
| Database | SQLite (WAL mode) |
| Vector Store | ChromaDB |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM (current) | Groq (3-key rotation) |
| LLM (target) | Fine-tuned Llama 3.1 8B via Ollama |
| ML Framework | PyTorch + scikit-learn |
| RL Framework | Stable-Baselines3 (PPO) |
| RL Environment | Gymnasium |
| Market Data | yfinance + Deriv WebSocket |
| Broker (personal) | Deriv |
| Broker (prop firm) | TradeLocker |
| Agent Orchestration | LangGraph StateGraph |
| MCP Protocol | FastMCP |

---

## Tasks → Subtasks

---

### T1 — Expert Trader Data Pipeline

- T1.1 Scrape TradingView top trader published ideas (symbol, TF, direction, entry, outcome)
- T1.2 Pull Myfxbook verified accounts trade history (open/close price, duration, result)
- T1.3 Pull copy-trading platform data (eToro / DupliTrade public stats)
- T1.4 Manual import: paste trade screenshots → parse with OCR or LLM
- T1.5 Normalize all sources into unified schema: `{symbol, timeframe, session, pattern, entry, sl, tp, result, trader_id}`
- T1.6 Label dataset quality score per trade (filter low-quality entries)
- T1.7 Store in SQLite `expert_trades` table
- T1.8 Build train / validation / test split pipeline

---

### T2 — Regime Detector

- T2.1 Feature engineering: ATR ratio, EMA spread, volume profile, ADX, session flag
- T2.2 Label historical data with regime (TRENDING / RANGING / VOLATILE / AVOID)
- T2.3 Train XGBoost classifier on labeled OHLC
- T2.4 Validate: confusion matrix, precision per regime class
- T2.5 Save model as `models/regime_detector.pkl`
- T2.6 Wrap into `RegimeDetector.predict(df)` class
- T2.7 Plug into agent pipeline — gate before signal engine

---

### T3 — LSTM Signal Engine

- T3.1 Build feature matrix: OHLC + EMA + RSI + ATR + MACD + session encoding
- T3.2 Build sequence windows per timeframe (50 candles → predict next move)
- T3.3 Train LSTM per timeframe (1m, 5m, 15m, 1h) — 4 separate models
- T3.4 Evaluate: accuracy, precision, recall per direction class
- T3.5 Save as `models/lstm_{timeframe}.pt`
- T3.6 Build `LSTMSignalEngine.score(df, timeframe)` → returns 0–100

---

### T4 — XGBoost Feature Scorer

- T4.1 Define feature set: 40+ technical indicators per candle
- T4.2 Label each candle with outcome (WIN / LOSS / NEUTRAL) from expert data
- T4.3 Train XGBoost on labeled feature matrix
- T4.4 SHAP analysis — understand which features drive predictions
- T4.5 Save as `models/signal_scorer.pkl`
- T4.6 Build `FeatureScorer.score(df)` → returns 0–100

---

### T5 — CNN Chart Pattern Recognition

- T5.1 Generate OHLC chart images from historical data (matplotlib → PNG)
- T5.2 Label images with pattern type (OB, FVG, BOS, ChoCH, Breakout, etc.)
- T5.3 Collect / augment labeled chart image dataset
- T5.4 Train CNN (ResNet18 transfer learning) on pattern images
- T5.5 Evaluate: per-pattern precision and recall
- T5.6 Save as `models/pattern_cnn.pt`
- T5.7 Build `PatternCNN.detect(df)` → returns pattern + confidence

---

### T6 — Ensemble Signal Gate

- T6.1 Build ensemble combiner: weighted average of LSTM + XGBoost + CNN scores
- T6.2 Calibrate weights using validation set performance
- T6.3 Set hard threshold: score ≥ 70 passes
- T6.4 Add agreement rule: all 3 models must agree on direction
- T6.5 Build `EnsembleGate.evaluate(df, timeframe)` → PASS / BLOCK + score

---

### T7 — Fine-tuned Llama 3.1 8B

- T7.1 Format expert trade dataset into instruction pairs: `{input: setup_context, output: trade_decision_reasoning}`
- T7.2 Set up Unsloth + QLoRA on Google Colab (free GPU)
- T7.3 Fine-tune Llama 3.1 8B on instruction dataset
- T7.4 Evaluate: trade decision accuracy vs expert ground truth
- T7.5 Export fine-tuned model (GGUF format for local inference)
- T7.6 Set up Ollama locally to serve the model
- T7.7 Replace Groq calls in Agent-03 with local Ollama endpoint
- T7.8 Periodic re-fine-tune as new expert data accumulates

---

### T8 — RL Position Manager

- T8.1 Build Gymnasium trading environment using historical OHLC
- T8.2 Define state space: current price, entry, SL distance, unrealized PnL, hold time, regime
- T8.3 Define action space: HOLD | MOVE_SL_BE | PARTIAL_CLOSE_50 | FULL_EXIT
- T8.4 Define reward function: PnL adjusted for drawdown penalty
- T8.5 Train PPO agent (Stable-Baselines3) on simulated environment
- T8.6 Validate agent on out-of-sample data
- T8.7 Save as `models/rl_position_manager.zip`
- T8.8 Replace static breakeven logic in Agent-05 with RL agent decisions
- T8.9 Continue RL training on live trade outcomes (online learning)

---

### T9 — Self-Learning Loop

- T9.1 Auto-index every closed trade into RAG on position close
- T9.2 Build weekly XGBoost retraining job (new labeled trades → retrain scorer)
- T9.3 Build monthly Llama fine-tune trigger (accumulate N new trades → re-tune)
- T9.4 Build RL environment updater (add live trade episodes to replay buffer)
- T9.5 Build performance dashboard: model accuracy vs live results over time
- T9.6 Alert system: notify if model accuracy drops below threshold (model drift detection)

---

### T10 — Infrastructure

- T10.1 Multi-timeframe data cache (SQLite `ohlc_cache`, refresh every 5 min)
- T10.2 Model versioning: save each trained model with timestamp + performance metrics
- T10.3 A/B testing: run new model alongside old, compare live results before switching
- T10.4 Kill switch: instant bot shutdown if daily DD breached
- T10.5 VPS setup for 24/7 running (Linux, 8GB RAM minimum)
- T10.6 Monitoring dashboard: live model confidence, regime, open trades, equity curve

---

### T11 — Dual Trading Mode (Prop Firm + Personal)

- T11.1 Add `TRADING_MODE=propfirm | personal | both` to `.env` and `config.py`
- T11.2 Add `PERSONAL_RISK_PCT`, `PERSONAL_MAX_DD_PCT`, `PERSONAL_DAILY_LOSS_LIMIT` to `.env`
- T11.3 Update Agent-04 (Risk Guardian):
  - `propfirm` → enforce firm DD rules, lot limits, stage rules
  - `personal` → enforce only personal risk params, no firm ceiling
- T11.4 Update `core/mcp_client.py`:
  - `propfirm` → `broker = tradelocker`
  - `personal` → `broker = deriv`
- T11.5 Update Agent-05 (Executor):
  - `propfirm` → place order via TradeLocker
  - `personal` → place order via Deriv (stake-based)
- T11.6 Update Streamlit UI:
  - Mode toggle on dashboard (PROP FIRM / PERSONAL)
  - Color coded: orange for prop firm, blue for personal
  - Show separate account stats per mode
- T11.7 Tag every trade in journal with `trading_mode`
- T11.8 Separate analytics per mode — never mix prop firm and personal trades
- T11.9 Allow both modes simultaneously on different accounts (parallel execution)
- T11.10 Kill switch per mode — stop prop firm without affecting personal, and vice versa

---

## Environment Variables

```bash
# ── Trading Mode ───────────────────────────────────────────
TRADING_MODE=personal               # propfirm | personal | both

# ── Personal Account ───────────────────────────────────────
PERSONAL_RISK_PCT=2.0
PERSONAL_MAX_DD_PCT=20.0
PERSONAL_DAILY_LOSS_LIMIT=5.0

# ── Deriv (Personal Broker) ────────────────────────────────
DERIV_API_KEY=                      # demo key
DERIV_API_KEY_REAL=                 # real key
DERIV_ACCOUNT_ID=VRTC6144147        # demo
DERIV_ACCOUNT_ID_REAL=CR3988560     # real
DERIV_MODE=demo                     # demo | real

# ── TradeLocker (Prop Firm Broker) ─────────────────────────
TRADELOCKER_BASE_URL=https://demo.tradelocker.com/backend-api
TRADELOCKER_EMAIL=
TRADELOCKER_PASSWORD=
TRADELOCKER_SERVER=
TRADELOCKER_ACCOUNT_ID=

# ── Active Prop Firm ───────────────────────────────────────
ACTIVE_PROP_FIRM=FundedNext
ACTIVE_ACCOUNT_ID=

# ── FundedNext ─────────────────────────────────────────────
FUNDEDNEXT_EMAIL=
FUNDEDNEXT_PASSWORD=
FUNDEDNEXT_ACCOUNT_ID=

# ── LLM ────────────────────────────────────────────────────
GROQ_API_KEY=                       # current (3-key rotation)
GROQ_API_KEY_2=
GROQ_API_KEY_3=
OLLAMA_URL=http://localhost:11434   # future: fine-tuned Llama
OLLAMA_MODEL=dudubot-llama          # future: fine-tuned model name

# ── Risk ───────────────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT=1.0
MIN_SIGNAL_SCORE=7.5
MIN_WIN_RATE_PCT=65.0
ENSEMBLE_PASS_THRESHOLD=70          # future: ML ensemble gate
```

---

## Current Status

| Component | Status |
|-----------|--------|
| FastAPI + Streamlit UI | Done |
| SQLite database | Done |
| Deriv broker (demo + real) | Done |
| RAG pipeline (ChromaDB) | Done |
| Backtest engine + runner | Done |
| Groq LLM (3-key rotation) | Done |
| 8-agent pipeline structure | Done |
| Basic signal scoring | Done |
| **T1 — Expert Data Pipeline** | Not started |
| **T2 — Regime Detector** | Not started |
| **T3 — LSTM Signal Engine** | Not started |
| **T4 — XGBoost Feature Scorer** | Not started |
| **T5 — CNN Pattern Recognition** | Not started |
| **T6 — Ensemble Signal Gate** | Not started |
| **T7 — Fine-tuned Llama 3.1** | Not started |
| **T8 — RL Position Manager** | Not started |
| **T9 — Self-Learning Loop** | Not started |
| **T10 — Infrastructure** | Not started |
| **T11 — Dual Trading Mode** | Not started |
