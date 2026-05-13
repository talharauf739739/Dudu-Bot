-- ForgeX AI — PostgreSQL Schema
-- Run: psql -d forgex_db -f database/schema.sql

CREATE TABLE IF NOT EXISTS trades (
    trade_id      SERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    instrument    VARCHAR(12) NOT NULL,
    direction     VARCHAR(4)  NOT NULL,          -- BUY | SELL
    strategy_id   VARCHAR(6)  NOT NULL,          -- S-01 … S-10
    timeframe     VARCHAR(5)  NOT NULL,          -- 1min | 5min
    session       VARCHAR(10) NOT NULL,          -- LONDON | NY
    entry_price   DECIMAL(12,5) NOT NULL,
    sl_price      DECIMAL(12,5) NOT NULL,
    tp_price      DECIMAL(12,5) NOT NULL,
    risk_rr       DECIMAL(4,2) NOT NULL,
    lot_size      DECIMAL(6,3) NOT NULL,
    result        VARCHAR(8),                    -- WIN | LOSS | BE | BLOCKED
    close_price   DECIMAL(12,5),
    pnl_usd       DECIMAL(10,2),
    hold_time_s   INTEGER,
    prop_firm     VARCHAR(20) NOT NULL,
    account_id    VARCHAR(20) NOT NULL,
    daily_dd_pct  DECIMAL(5,2),
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent       VARCHAR(30) NOT NULL,
    level       VARCHAR(10) NOT NULL DEFAULT 'INFO',
    message     TEXT NOT NULL,
    trade_id    INTEGER REFERENCES trades(trade_id)
);

CREATE TABLE IF NOT EXISTS drawdown_tracker (
    id           SERIAL PRIMARY KEY,
    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prop_firm    VARCHAR(20) NOT NULL,
    account_id   VARCHAR(20) NOT NULL,
    daily_dd_pct DECIMAL(5,2) NOT NULL,
    total_dd_pct DECIMAL(5,2) NOT NULL,
    balance      DECIMAL(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id           SERIAL PRIMARY KEY,
    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol       VARCHAR(12) NOT NULL,
    timeframe    VARCHAR(5) NOT NULL,
    pattern      VARCHAR(50) NOT NULL,
    score        DECIMAL(4,2) NOT NULL,
    session      VARCHAR(10) NOT NULL,
    direction    VARCHAR(4),
    passed       BOOLEAN NOT NULL DEFAULT FALSE,  -- passed Agent-02 threshold
    trade_id     INTEGER REFERENCES trades(trade_id)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_trades_timestamp    ON trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_strategy     ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_instrument   ON trades(instrument);
CREATE INDEX IF NOT EXISTS idx_trades_prop_firm    ON trades(prop_firm, account_id);
CREATE INDEX IF NOT EXISTS idx_trades_result       ON trades(result);
CREATE INDEX IF NOT EXISTS idx_agent_logs_agent    ON agent_logs(agent, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dd_tracker_firm     ON drawdown_tracker(prop_firm, account_id, timestamp DESC);
