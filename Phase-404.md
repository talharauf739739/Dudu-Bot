# Phase-404 Strategy v2.2

## Core Logic

**Asian Range → Post-Asian Sweep → BOS on M1 → OTE 0.618 → 1:2R**

> **Philosophy:** Trade the retest after a liquidity sweep, in the direction of the trend — that's Phase-404.
> Institutions fake a move against the trend (sweeping Asian H/L liquidity), then continue the real direction.
> You enter at the 0.618 retracement of that snap-back move, with the trend.

---

## Trade Window

| Time (UTC) | Session | Action |
|------------|---------|--------|
| 01:00–05:00 | Asian | Mark range only — NO trades |
| **05:00–08:00** | **Pre-London + London Open (1h)** | **✅ ONLY trade window** |
| 08:00+ | London mid-day | Skip — no entries |

> Trade the sweep of the Asian range immediately after Asian session closes,
> through the first hour of London. This is the highest-probability window
> for liquidity grabs and clean BOS.

---

## Step-by-Step Rules

### Step 1 — Mark Asian Range
- Session: 01:00–05:00 UTC (20:00–00:00 EST)
- Record the highest high and lowest low
- **Skip day if range < 10 pips (EURUSD) or < 20 pips (GBPJPY)**

### Step 2 — Wait for Liquidity Sweep (05:00–08:00 UTC only)
- Price wicks above Asian High OR below Asian Low
- Wick must be ≥ 8% of Asian range
- Confirmed when price **closes back inside** the range
- Rolling 5-candle window (sweeps can span 5 M1 candles)
- **Any sweep outside 05:00–08:00 UTC is ignored**

### Step 3 — Break of Structure (BOS) on M1
- SELL: close below the swing low (20-bar lookback) by ≥ 2 pips
- BUY: close above the swing high (20-bar lookback) by ≥ 2 pips
- Setup span (sweep extreme → BOS level) must be ≥ 7 pips
- HTF filter: 1h EMA(50) must align with direction

### Step 4 — OTE 0.618 Entry, 1:2 R:R
- Draw Fibonacci from sweep extreme to BOS level
- Limit order at **0.618 retracement**
- **Target: 1:2 Risk:Reward — fixed, no breakeven**
- **SL per pair** (beyond the sweep wick extreme):

| Pair | SL Pips | Reason |
|------|---------|--------|
| EURUSD | 10 pips | Tight range, clean structure |
| GBPUSD | 12 pips | Slightly wider wicks than EUR |
| USDJPY | 15 pips | Tokyo session wicks deeper |
| GBPJPY | 18 pips | High volatility, larger sweeps |

- SELL: SL = sweep high + N pips
- BUY: SL = sweep low − N pips
- **Max hold:** 3 trading days

---

## Filter Checklist

- [ ] Asian range ≥ min for the pair (EUR/GBP ≥10p · USDJPY ≥15p · GBPJPY ≥20p)
- [ ] Sweep between **05:00–08:00 UTC**
- [ ] Wick ≥ 8% of Asian range, closes back inside (rolling 5-candle window)
- [ ] BOS on M1 — clears swing by ≥ 2 pips
- [ ] BOS candle body ≥ 40% of candle range (strong directional close)
- [ ] Setup span ≥ 7 pips
- [ ] **1h EMA(50) aligned with direction** (medium trend)
- [ ] **Daily EMA(50) aligned with direction** (macro trend — both must agree)
- [ ] Place 0.618 limit → SL per-pair pips → TP at 1:2R (fixed, no BE)

---

## Risk Parameters

| Parameter | Value |
|-----------|-------|
| Timeframe | 1-minute (M1) |
| Risk per trade | 1% of account |
| Entry | OTE 0.618 limit |
| SL | Per-pair (10–18 pips beyond sweep) |
| TP | 1:2 R:R (fixed) |
| Breakeven | ❌ None — let trade run to SL or TP |
| Max hold | 3 trading days |
| Max trades | 1 per pair per day |

---

## Pairs

| Pair | Role | Asian Range | SL Pips |
|------|------|-------------|---------|
| EURUSD | Primary | 10–20 pips | 10 |
| GBPUSD | Primary | 12–22 pips | 12 |
| USDJPY | Secondary | 15–30 pips | 15 |
| GBPJPY | Secondary | 20–50 pips | 18 |

---

## Version History

| Version | Changes |
|---------|---------|
| v1.0 | Asian range + sweep + BOS + OTE 0.5/0.618/0.75 all levels |
| v2.0 | London killzone 07:00-10:00, min filters, HTF bias, 0.618 only, 1:3R, BE |
| v2.1 | Window 05:00–08:00 UTC (post-Asian + 1h London), 1:2R, min range relaxed |
| v2.2 | 4 pairs, per-pair SL pips, dual HTF (1h+Daily EMA50), BOS body ≥40%, black trade zone box |
