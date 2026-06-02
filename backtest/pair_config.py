"""
Phase-404 Per-Pair Strategy Configuration v3.0
================================================
Pairs: EURUSD and GBPJPY only
Data:  1m candles (yfinance 4×7d chunks → Redis accumulates weekly)

Accumulation plan:
  Each weekly run adds 7 days of 1m history to Redis.
  At 3-4 setups/week per pair → 50 trades in ~3-4 months.
  At 50 trades: statistically valid to confirm 70-80% WR.

Philosophy: "Trade the retest after a liquidity sweep, in the direction of the trend."

No EMA/HTF filter — the sweep IS the temporary counter-move.
Session bias: last 2 daily closes as direction gate (not lagging EMA).
"""

from dataclasses import dataclass


@dataclass
class PairConfig:
    # ── Identity ──────────────────────────────────────────────────────────────
    symbol:   str
    ticker:   str
    pip:      float
    pip_val:  float

    # ── Risk ──────────────────────────────────────────────────────────────────
    sl_pips:   int
    rr:        float = 2.0
    ote_level: float = 0.618

    # ── Asian Range ───────────────────────────────────────────────────────────
    min_asian_range_pips: int = 10

    # ── Sweep Detection ───────────────────────────────────────────────────────
    min_wick_pct:   float = 0.08   # sweep wick as % of Asian range
    min_wick_pips:  int   = 3      # minimum absolute pip size of sweep wick
    sweep_lookback: int   = 5      # rolling window candles

    # ── BOS Detection ─────────────────────────────────────────────────────────
    bos_lookback:      int = 20    # bars before sweep for swing ref (20m on 1m)
    bos_scan_forward:  int = 240   # bars after sweep to find BOS  (4h on 1m)
    bos_strength_pips: int = 2     # BOS must clear swing by >= N pips

    # ── Setup Quality ─────────────────────────────────────────────────────────
    min_setup_pips:     int = 8    # sweep-to-BOS span >= N pips
    min_fib_range_pips: int = 10   # fib range >= N pips (OTE zone quality)

    # ── Session Momentum Bias ─────────────────────────────────────────────────
    # Last N daily closes determine direction preference.
    # Both bearish → prefer SELL. Both bullish → prefer BUY. Mixed → allow both.
    use_session_bias:  bool = True
    session_bias_days: int  = 2

    # ── Trade Window (UTC hours) ──────────────────────────────────────────────
    kill_start: int = 5
    kill_end:   int = 9

    # ── Simulation (1m bars) ──────────────────────────────────────────────────
    forward_scan: int = 4320   # 3 trading days × 1440 min/day

    # ── Validation Target ────────────────────────────────────────────────────
    min_trades_for_validity: int = 50

    def summary(self) -> str:
        bias = f"Session{self.session_bias_days}d" if self.use_session_bias else "NoBias"
        return (f"{self.symbol}  SL={self.sl_pips}p  "
                f"AsR≥{self.min_asian_range_pips}p  "
                f"Wick≥{self.min_wick_pips}p(abs)  "
                f"BOS±{self.bos_scan_forward}bars  "
                f"Fib≥{self.min_fib_range_pips}p  "
                f"{bias}  "
                f"{self.kill_start:02d}:00–{self.kill_end:02d}:00 UTC")


# ─────────────────────────────────────────────────────────────────────────────
# EURUSD
# Tight Asian range, clean London sweeps, fast BOS on 1m.
# 3-pip absolute wick filters noise (% alone allows 0.8-pip wicks on 10p range).
# BOS lookback 20 bars = 20-min swing reference — recent, easy to break cleanly.
# Fib range ≥ 10 pips so OTE entry is ≥ 4 pips from SL (1:2R meaningful).
# Kill window 05:00-08:00 UTC — pure London open hour.
# ─────────────────────────────────────────────────────────────────────────────
EURUSD = PairConfig(
    symbol="EURUSD", ticker="EURUSD=X",
    pip=0.0001, pip_val=10.0, sl_pips=10,
    min_asian_range_pips=8,
    min_wick_pct=0.08, min_wick_pips=1, sweep_lookback=5,
    bos_lookback=20, bos_scan_forward=240,
    bos_strength_pips=0,   # any close beyond swing = valid BOS on 1m
    min_setup_pips=5, min_fib_range_pips=8,
    use_session_bias=False, session_bias_days=1,
    kill_start=5, kill_end=8,
    forward_scan=4320,
)

# ─────────────────────────────────────────────────────────────────────────────
# GBPJPY
# Violent sweeps, large ranges, wide kill window.
# 8-pip absolute wick — on 20-pip Asian range, 8% = only 1.6 pips, way too small.
# BOS lookback 20 bars = 20-min swing — fast structure in volatile pair.
# Fib range ≥ 20 pips — small setups on GBPJPY get stopped by spread + volatility.
# Kill window 05:00-09:00 UTC — wider because GBPJPY sweeps vary in timing.
# ─────────────────────────────────────────────────────────────────────────────
GBPJPY = PairConfig(
    symbol="GBPJPY", ticker="GBPJPY=X",
    pip=0.01, pip_val=7.0, sl_pips=18,
    min_asian_range_pips=15,
    min_wick_pct=0.07, min_wick_pips=2, sweep_lookback=7,  # 2p abs — real GBPJPY wick
    bos_lookback=20, bos_scan_forward=240,
    bos_strength_pips=0,   # any close beyond swing = valid BOS
    min_setup_pips=8, min_fib_range_pips=10,
    use_session_bias=False, session_bias_days=1,
    kill_start=5, kill_end=9,
    forward_scan=4320,
)

PAIR_CONFIGS: dict[str, PairConfig] = {
    "EURUSD": EURUSD,
    "GBPJPY": GBPJPY,
}
