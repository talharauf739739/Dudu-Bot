-- ForgeX AI — SQLite Schema
-- Auto-applied on first run via mcp_journal server.

CREATE TABLE IF NOT EXISTS trades (
    trade_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL DEFAULT (datetime('now')),
    instrument    TEXT    NOT NULL,
    direction     TEXT    NOT NULL,           -- BUY | SELL
    strategy_id   TEXT    NOT NULL,           -- S-01 … S-10
    timeframe     TEXT    NOT NULL,           -- 1min | 5min | 1h
    session       TEXT    NOT NULL,           -- LONDON | NY
    entry_price   REAL    NOT NULL,
    sl_price      REAL    NOT NULL,
    tp_price      REAL    NOT NULL,
    risk_rr       REAL    NOT NULL,
    lot_size      REAL    NOT NULL,
    result        TEXT,                       -- WIN | LOSS | BE | BLOCKED
    close_price   REAL,
    pnl_usd       REAL,
    hold_time_s   INTEGER,
    prop_firm     TEXT    NOT NULL,
    account_id    TEXT    NOT NULL,
    daily_dd_pct  REAL,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    agent       TEXT    NOT NULL,
    level       TEXT    NOT NULL DEFAULT 'INFO',
    message     TEXT    NOT NULL,
    trade_id    INTEGER REFERENCES trades(trade_id)
);

CREATE TABLE IF NOT EXISTS drawdown_tracker (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL DEFAULT (datetime('now')),
    prop_firm    TEXT    NOT NULL,
    account_id   TEXT    NOT NULL,
    daily_dd_pct REAL    NOT NULL,
    total_dd_pct REAL    NOT NULL,
    balance      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol       TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    pattern      TEXT    NOT NULL,
    score        REAL    NOT NULL,
    session      TEXT    NOT NULL,
    direction    TEXT,
    passed       INTEGER NOT NULL DEFAULT 0,  -- 0=false, 1=true
    trade_id     INTEGER REFERENCES trades(trade_id)
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    strategy_id      TEXT    NOT NULL,
    symbol           TEXT    NOT NULL,
    timeframe        TEXT    NOT NULL,
    prop_firm        TEXT    NOT NULL,
    total_trades     INTEGER NOT NULL DEFAULT 0,
    wins             INTEGER NOT NULL DEFAULT 0,
    losses           INTEGER NOT NULL DEFAULT 0,
    win_rate         REAL    NOT NULL DEFAULT 0,
    net_pnl_usd      REAL    NOT NULL DEFAULT 0,
    net_pnl_pct      REAL    NOT NULL DEFAULT 0,
    avg_rr           REAL    NOT NULL DEFAULT 0,
    max_drawdown_pct REAL    NOT NULL DEFAULT 0,
    profit_factor    REAL    NOT NULL DEFAULT 0,
    blocked_trades   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ohlc_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL DEFAULT 0,
    UNIQUE(symbol, timeframe, ts)
);

CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_tf  ON ohlc_cache(symbol, timeframe, ts DESC);
CREATE INDEX IF NOT EXISTS idx_bt_strategy     ON backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_bt_symbol       ON backtest_results(symbol);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp   ON trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_strategy    ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_instrument  ON trades(instrument);
CREATE INDEX IF NOT EXISTS idx_trades_prop_firm   ON trades(prop_firm, account_id);
CREATE INDEX IF NOT EXISTS idx_trades_result      ON trades(result);
CREATE INDEX IF NOT EXISTS idx_agent_logs_agent   ON agent_logs(agent, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dd_tracker_firm    ON drawdown_tracker(prop_firm, account_id, timestamp DESC);
