# Phase-404 — Status Report · 2 June 2026

---

## Where We Stand

### System Architecture

| Component | Status | Detail |
|-----------|--------|--------|
| Data Store | ✅ Live | Redis (localhost:6379) — accumulates 1m candles weekly |
| Data Source | ✅ Working | yfinance — 4 × 7-day chunks = ~28 days per run |
| Backtest Engine | ✅ Working | `phase404_pro.py` — true 1m candles |
| Signal Generator | ✅ Working | `phase404_signals.py` — sweep + BOS + OTE |
| Per-pair Config | ✅ Working | `pair_config.py` — EURUSD + GBPJPY independently tuned |
| Report | ✅ Working | `data/phase404/phase404_pro_report.html` |

### Commands

```bash
# Add 7 new days of 1m data + run backtest
python -m backtest.phase404_pro --update

# Run backtest on stored data only (no download)
python -m backtest.phase404_pro

# Check Redis storage status
python -m backtest.data_store status
```

---

## Current Backtest Results (4 weeks · May 4 – Jun 1, 2026)

| Pair | Setups | Per Week | Trades | WR | Net P&L |
|------|--------|----------|--------|----|---------|
| EURUSD | 2 | 0.5/wk | 1 | 0% | -$100 |
| GBPJPY | 7 | 1.75/wk | 7 | 57% | +$497 |
| **Total** | **9** | **2.25/wk** | **8** | **50%** | **+$397** |

> **Statistical note:** 8 trades is not enough to validate anything. Need **50 trades per pair** before WR means anything. Run weekly — GBPJPY reaches 50 trades in ~7 months at current rate.

---

## What Was Fixed (Full Journey)

| Problem | Root Cause | Fix |
|---------|-----------|-----|
| 0 EURUSD setups | BOS body filter = 0% on yfinance 1m flat candles | Removed body filter |
| 692 filter spam | `used_dates` not set on rejections | Set on every rejection |
| 1H HTF self-defeating | Sweep happens when 1H is temporarily counter-direction | Removed 1H filter |
| 0 GBPJPY BOS found | `detect_bos` hardcoded 60-bar scan (1h) | Now 240-bar scan (4h) |
| Redis dedup bug | JSON value used as key, flat candles identical | Added timestamp to member key |
| forward_scan 8h | 480 bars × 1m = 8h max hold | Changed to 4320 bars = 3 days |

---

## Phase-404 Strategy — EURUSD

### Core Logic

> **"Trade the retest after a liquidity sweep, in the direction of the trend."**

Asian range forms while London is asleep. London opens and aggressively grabs liquidity above or below the range. Price snaps back. Enter at the 61.8% retracement of the sweep-to-BOS move.

### Setup Rules

**Step 1 — Mark Asian Range (01:00–05:00 UTC)**
- Record the highest high and lowest low of the session
- Skip the day if range < 8 pips (too tight, sweep will be noise)

**Step 2 — Liquidity Sweep (05:00–08:00 UTC only)**
- Price wicks above Asian High → **BEAR sweep** (fake breakout above)
- Price wicks below Asian Low → **BULL sweep** (fake breakdown below)
- Sweep wick must be ≥ 8% of Asian range AND ≥ 1 pip absolute beyond the level
- Rolling 5-candle window (sweep can span multiple 1m bars)
- Close must come back inside the Asian range to confirm

**Step 3 — Break of Structure (BOS) on 1m**
- After sweep, wait for price to break the 20-bar swing reference
- BEAR sweep → BOS = any close below the 20-bar swing low
- BULL sweep → BOS = any close above the 20-bar swing high
- BOS must occur within 240 candles (4 hours) of the sweep
- Minimum fib range (sweep-to-BOS): ≥ 8 pips

**Step 4 — OTE Entry**
- Draw Fibonacci from sweep extreme to BOS level
- Place limit order at **0.618 retracement**
- SL: 10 pips beyond the sweep wick extreme
  - SELL: SL = sweep high + 10 pips
  - BUY: SL = sweep low − 10 pips
- TP: **1:2 R:R** (fixed, no breakeven, no trailing)
- Max hold: 3 trading days (4320 × 1m bars)

### EURUSD Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| Timeframe | 1m | Entry precision |
| Trade window | 05:00–08:00 UTC | London open only |
| Min Asian range | 8 pips | Smaller = noise |
| Sweep wick min | 1 pip absolute | Calibrated to real EUR wicks (1.3–2p typical) |
| Sweep wick % | 8% of range | Quality threshold |
| BOS lookback | 20 bars (20 min) | Recent structure breaks fastest |
| BOS scan | 240 bars (4h) | Give price time to break |
| Min fib range | 8 pips | OTE must have meaningful distance |
| SL | 10 pips beyond sweep | EUR is clean, tight SL valid |
| TP | 1:2 R:R | Fixed |
| No HTF filter | — | Sweep = counter-1H move by definition |
| No session bias | — | Let 50 trades reveal real edge |

### What We Know About EURUSD

- Currently ~0.5 setups/week in May 2026 data window
- May 2026 was a consolidation/declining period for EURUSD (1.13→1.17 rally stalling)
- Only 1 trade so far — insufficient for any conclusion
- **Milestone: run weekly until 25 trades, then review WR**

---

## Phase-404 Strategy — GBPJPY

### Core Logic

Same philosophy as EURUSD but adapted for GBPJPY's volatility and range profile.

> GBPJPY is "The Beast" — wide Asian ranges (20–50 pips), violent sweeps, faster structure breaks. Both SELL and BUY setups work but the pair is highly trend-sensitive.

### Setup Rules

**Step 1 — Mark Asian Range (01:00–05:00 UTC)**
- Record highest high and lowest low
- Skip the day if range < 15 pips (GBPJPY needs room for a meaningful sweep)

**Step 2 — Liquidity Sweep (05:00–09:00 UTC)**
- Wider window than EURUSD — GBPJPY sweeps can arrive up to 09:00 UTC
- Wick must be ≥ 7% of Asian range AND ≥ 2 pips absolute beyond the level
- Rolling 7-candle window (GBPJPY sweeps span more candles due to volatility)
- Close must come back inside the range

**Step 3 — Break of Structure (BOS) on 1m**
- 20-bar swing lookback (same as EURUSD — short lookback works for fast-moving GBPJPY)
- Any close beyond the swing reference = valid BOS (no pip strength requirement)
- BOS must occur within 240 candles (4 hours)
- Minimum fib range (sweep-to-BOS): ≥ 10 pips

**Step 4 — OTE Entry**
- Fibonacci from sweep extreme to BOS level
- Limit order at **0.618 retracement**
- SL: 18 pips beyond the sweep wick extreme
  - SELL: SL = sweep high + 18 pips
  - BUY: SL = sweep low − 18 pips
- TP: **1:2 R:R** (fixed)
- Max hold: 3 trading days

### GBPJPY Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| Timeframe | 1m | Entry precision |
| Trade window | 05:00–09:00 UTC | Wider — GBPJPY sweeps vary in timing |
| Min Asian range | 15 pips | Volatile pair needs more room |
| Sweep wick min | 2 pips absolute | Calibrated to real GBP/JPY wicks (2–8p typical) |
| Sweep wick % | 7% of range | Slightly looser than EUR |
| BOS lookback | 20 bars (20 min) | Structure breaks fast on GBPJPY |
| BOS scan | 240 bars (4h) | Same window |
| Min fib range | 10 pips | Meaningful distance for volatile pair |
| SL | 18 pips beyond sweep | Wide wicks need buffer |
| TP | 1:2 R:R | Fixed |
| No HTF filter | — | Same reason as EURUSD |
| No session bias | — | Let 50 trades reveal edge |

### What We Know About GBPJPY

- **7 setups in 4 weeks = 1.75/week** — closest to target 3-4/week
- **57% WR on 7 trades** — promising but statistically insufficient
- **SELL setups outperform BUY** in May 2026 (market was declining from 215+ peak)
  - SELL: 2/2 = 100% WR
  - BUY: 2/5 = 40% WR
- When 50 trades are accumulated: if SELL WR stays high, consider adding session bias back
- **Milestone: reach 25 trades (~3-4 months), review SELL vs BUY split**

---

## Accumulation Plan

```
Today (Jun 2):    8 trades total across both pairs
+1 month:         ~17 trades   (run --update weekly)
+3 months:        ~40 trades   ← first meaningful read on WR
+5 months:        ~50 trades   ← EURUSD validated
+7 months:        ~70 trades   ← GBPJPY fully validated
```

**Weekly command (every Monday):**
```bash
python -m backtest.phase404_pro --update
```

---

## Pending Decisions (Revisit at 25 Trades)

1. **Session bias** — if WR < 60% at 25 trades, add `use_session_bias=True` to GBPJPY
2. **EURUSD setup rate** — still too low (0.5/wk). May need to widen kill window to 05:00–09:00 UTC
3. **SELL-only GBPJPY** — if SELL WR stays 80%+ and BUY WR stays < 40%, restrict to SELL only
4. **SL pip tuning** — 10p EUR / 18p GBPJPY can be adjusted after seeing sl_dist on losses

---

## Key Files

| File | Purpose |
|------|---------|
| `backtest/phase404_pro.py` | Main backtest engine + HTML report |
| `backtest/pair_config.py` | Per-pair strategy parameters |
| `backtest/data_store.py` | Redis 1m data store + yfinance downloader |
| `backtest/phase404_signals.py` | Core sweep/BOS/OTE detection |
| `Phase-404.md` | Strategy documentation v2.2 |
| `data/phase404/phase404_pro_report.html` | Latest backtest HTML report |
