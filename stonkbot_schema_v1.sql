-- stonkbot_schema_v1.sql
-- SQLite schema for StonkBOT.AI core data
-- Run: sqlite3 /opt/stonk-ai/stonkbot.db < stonkbot_schema_v1.sql
--
-- Design principles:
-- - Single source of truth (no more dual JSON writers)
-- - WAL mode for concurrent reads during writes
-- - JSON export kept as read-only mirror for website
-- - All timestamps stored as UTC ISO-8601 text

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ---------------------------------------------------------------------------
-- 1. SIGNALS (replaces signals.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    company_name    TEXT,
    sector          TEXT,
    industry        TEXT,

    -- Core scores
    total_score     REAL,
    momentum_score  REAL,
    quality_score   REAL,
    risk_score      REAL,
    regime_score    REAL,

    -- Readiness & tier
    readiness_score INTEGER CHECK (readiness_score BETWEEN 0 AND 100),
    backend_tier    TEXT,
    frontend_tier   TEXT CHECK (frontend_tier IN ('PRIME','BUILDING','WATCHING','TRACKING')),
    status          TEXT CHECK (status IN ('queued','add','hold','not_ready','tier_too_low','no_price')),

    -- Confirmation flags (10-factor readiness)
    confirm_signal       INTEGER DEFAULT 0,
    confirm_sector       INTEGER DEFAULT 0,
    confirm_ema          INTEGER DEFAULT 0,
    confirm_rsi          INTEGER DEFAULT 0,
    confirm_iv_skew      INTEGER DEFAULT 0,
    confirm_market       INTEGER DEFAULT 0,
    confirm_outlook      INTEGER DEFAULT 0,
    confirm_analyst      INTEGER DEFAULT 0,
    confirm_momentum     INTEGER DEFAULT 0,
    confirm_trend        INTEGER DEFAULT 0,

    -- Price / sizing
    price             REAL,
    atr_14            REAL,
    daily_volume      REAL,
    position_size_usd REAL,

    -- Metadata
    data_source       TEXT DEFAULT 'alpaca',
    run_id            TEXT,
    generated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at        TEXT,
    is_entry_eligible INTEGER DEFAULT 0,
    extra_json        TEXT  -- freeform JSON for extensibility
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_tier ON signals(frontend_tier);
CREATE INDEX IF NOT EXISTS idx_signals_entry ON signals(is_entry_eligible, frontend_tier);
CREATE INDEX IF NOT EXISTS idx_signals_generated ON signals(generated_at);

-- ---------------------------------------------------------------------------
-- 2. PORTFOLIO SNAPSHOTS (replaces portfolio_data.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cash_usd        REAL,
    equity_usd      REAL,
    total_value_usd REAL,
    day_pnl_usd     REAL,
    day_pnl_pct     REAL,
    total_pnl_usd   REAL,
    total_pnl_pct   REAL,
    open_positions  INTEGER,
    max_positions   INTEGER DEFAULT 12,
    margin_used_pct REAL,
    snapshot_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshot_at ON portfolio_snapshots(snapshot_at);

-- ---------------------------------------------------------------------------
-- 3. PORTFOLIO HOLDINGS (normalized from portfolio_data.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    shares          REAL,
    avg_entry_price REAL,
    current_price   REAL,
    market_value_usd REAL,
    unrealized_pnl_usd REAL,
    unrealized_pnl_pct REAL,
    day_pnl_usd     REAL,
    day_pnl_pct     REAL,
    cost_basis_usd  REAL,
    stop_price      REAL,
    atr_14          REAL,
    backend_tier    TEXT,
    frontend_tier   TEXT,
    sector          TEXT,
    added_at        TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    is_active       INTEGER DEFAULT 1,
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
CREATE INDEX IF NOT EXISTS idx_holdings_active ON holdings(is_active);

-- ---------------------------------------------------------------------------
-- 4. PORTFOLIO HISTORY (replaces portfolio_history.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL UNIQUE,
    cash        REAL,
    equity      REAL,
    total_value REAL,
    day_pnl     REAL,
    total_pnl   REAL,
    positions   INTEGER,
    benchmark_value REAL,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_portfolio_history_date ON portfolio_history(date);

-- ---------------------------------------------------------------------------
-- 5. WATCHLIST (replaces ai_watchlist_live.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL UNIQUE,
    company_name    TEXT,
    sector          TEXT,
    backend_tier    TEXT,
    frontend_tier   TEXT CHECK (frontend_tier IN ('PRIME','BUILDING','WATCHING','TRACKING')),
    readiness_score INTEGER CHECK (readiness_score BETWEEN 0 AND 100),
    status          TEXT CHECK (status IN ('queued','add','hold','not_ready','tier_too_low','no_price')),
    price           REAL,
    daily_change_pct REAL,
    volume_30d_avg  REAL,
    added_at        TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    data_source     TEXT DEFAULT 'alpaca',
    narratives      TEXT,  -- cached LLM narrative JSON
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_watchlist_tier ON watchlist(frontend_tier);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);

-- ---------------------------------------------------------------------------
-- 6. TRADES (new — unified from scattered sources)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    side            TEXT CHECK (side IN ('buy','sell')),
    qty             REAL,
    price           REAL,
    total_value_usd REAL,
    fees_usd        REAL,
    order_type      TEXT CHECK (order_type IN ('market','limit','stop')),
    alpaca_order_id TEXT,
    realized_pnl_usd  REAL,
    realized_pnl_pct  REAL,
    execution_time  TEXT,
    signal_id       INTEGER,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(execution_time);

-- ---------------------------------------------------------------------------
-- 7. HEARTBEATS (replaces heartbeat tracker files)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heartbeats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    job_type    TEXT,  -- 'cron' | 'systemd' | 'script'
    status      TEXT CHECK (status IN ('ok','fail','stale','skipped')),
    runtime_ms  INTEGER,
    message     TEXT,
    beat_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_job ON heartbeats(job_name, beat_at);

-- ---------------------------------------------------------------------------
-- 8. SYSTEM LOG (ad-hoc events, monitor findings, alerts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT CHECK (level IN ('debug','info','warn','error','critical')),
    source      TEXT,  -- script name
    message     TEXT NOT NULL,
    context_json TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_system_log_level ON system_log(level, created_at);
