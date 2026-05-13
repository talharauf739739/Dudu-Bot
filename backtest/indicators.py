"""
Technical indicators used by all 10 strategies.
Built on the `ta` library + pure pandas for custom logic.
"""

import pandas as pd
import numpy as np
import ta


# ── Basic ──────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return ta.trend.EMAIndicator(series, window=period).ema_indicator()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(series, window=period).rsi()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ind = ta.trend.MACD(series, window_fast=fast, window_slow=slow, window_sign=signal)
    return pd.DataFrame({
        "macd":   ind.macd(),
        "signal": ind.macd_signal(),
        "hist":   ind.macd_diff(),
    })


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=period
    ).average_true_range()


def keltner_channel(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    ind = ta.volatility.KeltnerChannel(
        df["high"], df["low"], df["close"],
        window=period, window_atr=period, multiplier=mult
    )
    return pd.DataFrame({
        "upper":  ind.keltner_channel_hband(),
        "mid":    ind.keltner_channel_mband(),
        "lower":  ind.keltner_channel_lband(),
    })


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP — resets each day."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, 1)  # avoid div-by-zero
    cum_vol = vol.groupby(df.index.date).cumsum()
    cum_tp_vol = (typical * vol).groupby(df.index.date).cumsum()
    return cum_tp_vol / cum_vol


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Convert OHLC to Heikin-Ashi candles."""
    ha = pd.DataFrame(index=df.index)
    ha["close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha["open"] = (df["open"].shift(1) + df["close"].shift(1)) / 2
    ha.iloc[0, ha.columns.get_loc("open")] = df["open"].iloc[0]
    ha["high"] = df[["high", "open", "close"]].max(axis=1)
    ha["low"]  = df[["low",  "open", "close"]].min(axis=1)
    return ha


# ── Structure (ICT / SMC) ──────────────────────────────────────────────────────

def swing_highs_lows(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Detect swing highs and lows over a rolling lookback window."""
    result = pd.DataFrame(index=df.index)
    result["swing_high"] = df["high"][
        (df["high"] == df["high"].rolling(lookback * 2 + 1, center=True).max())
    ]
    result["swing_low"] = df["low"][
        (df["low"] == df["low"].rolling(lookback * 2 + 1, center=True).min())
    ]
    return result


def detect_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fair Value Gap detection.
    Bullish FVG: candle[i-2].high < candle[i].low  (gap up)
    Bearish FVG: candle[i-2].low  > candle[i].high (gap down)
    """
    bull_fvg = df["low"] > df["high"].shift(2)
    bear_fvg = df["high"] < df["low"].shift(2)
    return pd.DataFrame({"bull_fvg": bull_fvg, "bear_fvg": bear_fvg}, index=df.index)


def detect_order_block(df: pd.DataFrame, lookforward: int = 3, move_mult: float = 1.5) -> pd.DataFrame:
    """
    Simplified Order Block detection.
    A candle is a bullish OB if it is bearish and is followed by a
    bullish move >= move_mult × its body size within lookforward candles.
    """
    body = (df["close"] - df["open"]).abs()
    avg_body = body.rolling(20).mean()

    bull_ob = pd.Series(False, index=df.index)
    bear_ob = pd.Series(False, index=df.index)

    for i in range(len(df) - lookforward):
        candle_body = body.iloc[i]
        if candle_body < avg_body.iloc[i] * 0.5:
            continue
        # Bullish OB: bearish candle followed by strong upward move
        if df["close"].iloc[i] < df["open"].iloc[i]:
            future_high = df["high"].iloc[i + 1: i + 1 + lookforward].max()
            if future_high - df["close"].iloc[i] >= candle_body * move_mult:
                bull_ob.iloc[i] = True
        # Bearish OB: bullish candle followed by strong downward move
        if df["close"].iloc[i] > df["open"].iloc[i]:
            future_low = df["low"].iloc[i + 1: i + 1 + lookforward].min()
            if df["close"].iloc[i] - future_low >= candle_body * move_mult:
                bear_ob.iloc[i] = True

    return pd.DataFrame({"bull_ob": bull_ob, "bear_ob": bear_ob}, index=df.index)


def detect_bos_choch(df: pd.DataFrame, swing_lookback: int = 10) -> pd.DataFrame:
    """
    Break of Structure and Change of Character detection.
    BOS_UP: price closes above recent swing high → bullish continuation
    BOS_DN: price closes below recent swing low  → bearish continuation
    CHOCH_UP: BOS_UP after series of lower highs → potential reversal to bullish
    CHOCH_DN: BOS_DN after series of higher lows → potential reversal to bearish
    """
    rolling_high = df["high"].rolling(swing_lookback).max()
    rolling_low  = df["low"].rolling(swing_lookback).min()

    bos_up = df["close"] > rolling_high.shift(1)
    bos_dn = df["close"] < rolling_low.shift(1)

    # ChoCH: opposite BOS after prevailing trend
    prev_trend_up = bos_up.rolling(swing_lookback).sum() == 0  # no recent bullish BOS
    prev_trend_dn = bos_dn.rolling(swing_lookback).sum() == 0

    choch_up = bos_up & prev_trend_up
    choch_dn = bos_dn & prev_trend_dn

    return pd.DataFrame({
        "bos_up":   bos_up,
        "bos_dn":   bos_dn,
        "choch_up": choch_up,
        "choch_dn": choch_dn,
    }, index=df.index)


def london_range(df: pd.DataFrame) -> pd.DataFrame:
    """
    For London Breakout strategy.
    Calculates 07:00-08:00 GMT range high and low per day.
    """
    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    pre_london = df.between_time("07:00", "07:59")
    daily_range = pre_london.groupby(pre_london.index.date).agg(
        range_high=("high", "max"),
        range_low=("low", "min"),
    )
    daily_range.index = pd.to_datetime(daily_range.index)

    result = pd.DataFrame(index=df.index)
    result["range_high"] = float("nan")
    result["range_low"] = float("nan")

    for date, row in daily_range.iterrows():
        mask = df.index.date == date.date()
        result.loc[mask, "range_high"] = row["range_high"]
        result.loc[mask, "range_low"] = row["range_low"]

    return result.ffill()
