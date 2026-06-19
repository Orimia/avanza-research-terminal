"""Schema migrations. Idempotent ``CREATE TABLE IF NOT EXISTS`` statements.

Versioned via the ``schema_meta`` table so future migrations can be additive.
"""
from __future__ import annotations

import contextlib
import sqlite3

SCHEMA_VERSION = 4

_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # -- always-on engine state -------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS signal_state (
        dedup_key    TEXT PRIMARY KEY,   -- symbol|type[|bucket]
        state_value  TEXT,               -- discrete state we last emitted on
        last_value   REAL,               -- last numeric trigger value
        last_emitted TEXT                -- ISO timestamp
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol      TEXT NOT NULL,
        type        TEXT NOT NULL,
        action      TEXT,
        severity    TEXT,
        title       TEXT NOT NULL,
        detail      TEXT,
        value       REAL,
        created_at  TEXT NOT NULL,
        sent        INTEGER NOT NULL DEFAULT 0,
        channels    TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts_log(created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        kind        TEXT NOT NULL,        -- intraday / morning / close / manual
        started_at  TEXT NOT NULL,
        finished_at TEXT,
        n_scanned   INTEGER DEFAULT 0,
        n_signals   INTEGER DEFAULT 0,
        status      TEXT,
        note        TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS data_cache (
        symbol      TEXT PRIMARY KEY,
        payload     TEXT NOT NULL,      -- JSON StockData
        fetched_at  TEXT NOT NULL,
        is_mock     INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        symbol   TEXT PRIMARY KEY,
        ticker   TEXT NOT NULL,
        exchange TEXT NOT NULL,
        added_at TEXT NOT NULL,
        note     TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio (
        symbol        TEXT PRIMARY KEY,
        ticker        TEXT NOT NULL,
        exchange      TEXT NOT NULL,
        shares        REAL NOT NULL,
        average_cost  REAL NOT NULL,
        currency      TEXT NOT NULL,
        current_price REAL,
        sector        TEXT,
        notes         TEXT,
        updated_at    TEXT NOT NULL
    );
    """,
    # -- crypto sleeve (separate from the equity portfolio so it never distorts
    #    equity weights or gets scanned by the equity engine) -----------------
    """
    CREATE TABLE IF NOT EXISTS crypto_holdings (
        symbol         TEXT PRIMARY KEY,    -- ticker.exchange e.g. BTC.CC
        ticker         TEXT NOT NULL,       -- BTC / ETH / SOL ...
        exchange       TEXT NOT NULL DEFAULT 'CC',
        shares         REAL NOT NULL,       -- fractional units held
        average_cost   REAL NOT NULL,       -- USD per unit
        currency       TEXT NOT NULL DEFAULT 'USD',
        current_price  REAL,
        sector         TEXT,
        notes          TEXT,
        kind           TEXT DEFAULT 'crypto',
        fixed_value_sek REAL,
        account        TEXT DEFAULT 'Coinbase',
        staked_pct     REAL,
        updated_at     TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS memos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol      TEXT NOT NULL,
        action      TEXT,
        confidence  TEXT,
        composite   REAL,
        memo        TEXT NOT NULL,      -- markdown
        created_at  TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memos_symbol ON memos(symbol);
    """,
]


# Additive column migrations (run best-effort; ignored if column already exists).
_ALTERS = [
    "ALTER TABLE portfolio ADD COLUMN kind TEXT DEFAULT 'stock'",
    "ALTER TABLE portfolio ADD COLUMN fixed_value_sek REAL",
]


def run_migrations(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for stmt in _STATEMENTS:
        cur.executescript(stmt)
    for alter in _ALTERS:
        with contextlib.suppress(sqlite3.OperationalError):
            cur.execute(alter)  # ignored if column already exists
    cur.execute(
        "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
