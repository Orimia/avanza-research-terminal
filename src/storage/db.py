"""SQLite database access layer."""
from __future__ import annotations

import contextlib
import os
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT
from src.models.schemas import Holding, StockData
from src.storage.migrations import run_migrations

# Honour TERMINAL_DB_PATH so tests can isolate the cache from the user's real DB.
DB_PATH = Path(os.getenv("TERMINAL_DB_PATH", str(PROJECT_ROOT / "data" / "terminal.db")))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        run_migrations(self.conn)

    # -- data cache --------------------------------------------------------
    def cache_get(self, symbol: str) -> Optional[tuple[StockData, datetime]]:
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM data_cache WHERE symbol=?", (symbol,)
        ).fetchone()
        if not row:
            return None
        data = StockData.model_validate_json(row["payload"])
        ts = datetime.fromisoformat(row["fetched_at"])
        return data, ts

    def cache_put(self, data: StockData) -> None:
        self.conn.execute(
            "INSERT INTO data_cache(symbol, payload, fetched_at, is_mock) "
            "VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "payload=excluded.payload, fetched_at=excluded.fetched_at, is_mock=excluded.is_mock",
            (data.symbol, data.model_dump_json(), _utcnow(), int(data.is_mock)),
        )
        self.conn.commit()

    # -- watchlist ---------------------------------------------------------
    def watchlist_add(self, ticker: str, exchange: str, note: str = "") -> None:
        symbol = f"{ticker}.{exchange}"
        self.conn.execute(
            "INSERT INTO watchlist(symbol, ticker, exchange, added_at, note) "
            "VALUES(?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET note=excluded.note",
            (symbol, ticker, exchange, _utcnow(), note),
        )
        self.conn.commit()

    def watchlist_remove(self, symbol: str) -> None:
        self.conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
        self.conn.commit()

    def watchlist_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT symbol, ticker, exchange, note FROM watchlist ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- portfolio ---------------------------------------------------------
    def portfolio_replace(self, holdings: list[Holding]) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM portfolio")
        for h in holdings:
            cur.execute(
                "INSERT INTO portfolio(symbol, ticker, exchange, shares, average_cost, "
                "currency, current_price, sector, notes, kind, fixed_value_sek, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (h.symbol, h.ticker, h.exchange, h.shares, h.average_cost,
                 h.currency, h.current_price, h.sector, h.notes, h.kind,
                 h.fixed_value_sek, _utcnow()),
            )
        self.conn.commit()
        self._auto_backup("portfolio")

    def portfolio_all(self) -> list[Holding]:
        rows = self.conn.execute(
            "SELECT ticker, exchange, shares, average_cost, currency, "
            "current_price, sector, notes, kind, fixed_value_sek FROM portfolio"
        ).fetchall()
        return [Holding(**dict(r)) for r in rows]

    # -- crypto sleeve (separate account, isolated from equity flows) ------
    def crypto_holdings_all(self) -> list[Holding]:
        rows = self.conn.execute(
            "SELECT ticker, exchange, shares, average_cost, currency, current_price, "
            "sector, notes, kind, fixed_value_sek, account, staked_pct FROM crypto_holdings"
        ).fetchall()
        return [Holding(**dict(r)) for r in rows]

    def crypto_holdings_replace(self, holdings: list[Holding]) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM crypto_holdings")
        for h in holdings:
            cur.execute(
                "INSERT INTO crypto_holdings(symbol, ticker, exchange, shares, average_cost, "
                "currency, current_price, sector, notes, kind, fixed_value_sek, account, "
                "staked_pct, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (h.symbol, h.ticker, h.exchange, h.shares, h.average_cost, h.currency,
                 h.current_price, h.sector, h.notes, h.kind, h.fixed_value_sek,
                 h.account, h.staked_pct, _utcnow()),
            )
        self.conn.commit()
        self._auto_backup("crypto")

    # -- memos -------------------------------------------------------------
    def memo_save(self, symbol: str, action: str, confidence: str,
                  composite: float, memo: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO memos(symbol, action, confidence, composite, memo, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (symbol, action, confidence, composite, memo, _utcnow()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def memo_history(self, symbol: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, action, confidence, composite, created_at FROM memos "
            "WHERE symbol=? ORDER BY id DESC LIMIT ?", (symbol, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- engine: signal state (de-dup) ------------------------------------
    def signal_state_get(self, dedup_key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT dedup_key, state_value, last_value, last_emitted "
            "FROM signal_state WHERE dedup_key=?", (dedup_key,)
        ).fetchone()
        return dict(row) if row else None

    def signal_state_set(self, dedup_key: str, state_value: str,
                         last_value: float | None = None,
                         touch_emitted: bool = True) -> None:
        """Upsert signal state. ``touch_emitted=False`` records the new state
        WITHOUT advancing ``last_emitted`` — used when we observe a state but
        don't alert, so cooldown/transition logic stays anchored to real alerts.
        """
        if touch_emitted:
            self.conn.execute(
                "INSERT INTO signal_state(dedup_key, state_value, last_value, last_emitted) "
                "VALUES(?,?,?,?) ON CONFLICT(dedup_key) DO UPDATE SET "
                "state_value=excluded.state_value, last_value=excluded.last_value, "
                "last_emitted=excluded.last_emitted",
                (dedup_key, state_value, last_value, _utcnow()),
            )
        else:
            self.conn.execute(
                "INSERT INTO signal_state(dedup_key, state_value, last_value, last_emitted) "
                "VALUES(?,?,?,NULL) ON CONFLICT(dedup_key) DO UPDATE SET "
                "state_value=excluded.state_value, last_value=excluded.last_value",
                (dedup_key, state_value, last_value),
            )
        self.conn.commit()

    # -- engine: alerts log -----------------------------------------------
    def alert_add(self, *, symbol: str, type: str, action: str | None, severity: str,
                  title: str, detail: str, value: float | None,
                  sent: bool, channels: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO alerts_log(symbol, type, action, severity, title, detail, "
            "value, created_at, sent, channels) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (symbol, type, action, severity, title, detail, value, _utcnow(),
             int(sent), channels),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def alerts_recent(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT symbol, type, action, severity, title, detail, value, created_at, "
            "sent, channels FROM alerts_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def alerts_since(self, iso_ts: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT symbol, type, action, severity, title, detail, value, created_at "
            "FROM alerts_log WHERE created_at >= ? ORDER BY id DESC", (iso_ts,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- engine: scan run health ------------------------------------------
    def scan_run_start(self, kind: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO scan_runs(kind, started_at, status) VALUES(?,?,?)",
            (kind, _utcnow(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def scan_run_finish(self, run_id: int, *, n_scanned: int, n_signals: int,
                        status: str, note: str = "") -> None:
        self.conn.execute(
            "UPDATE scan_runs SET finished_at=?, n_scanned=?, n_signals=?, status=?, note=? "
            "WHERE id=?",
            (_utcnow(), n_scanned, n_signals, status, note, run_id),
        )
        self.conn.commit()

    def scan_runs_recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT kind, started_at, finished_at, n_scanned, n_signals, status, note "
            "FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def last_scan_run(self) -> Optional[dict]:
        rows = self.scan_runs_recent(1)
        return rows[0] if rows else None

    # -- backups -----------------------------------------------------------
    def backup(self, *, keep: int = 10, reason: str = "auto") -> Optional[Path]:
        """Consistent online SQLite backup to ``data/backups/``, rotating to the
        newest ``keep`` files. Uses the live-connection backup API (safe even
        while the DB is in use). Returns the backup path.
        """
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        dst = backup_dir / f"{self.path.stem}-{stamp}-{reason}.db"
        dst_conn = sqlite3.connect(str(dst))
        try:
            self.conn.backup(dst_conn)        # online backup — consistent while in use
        finally:
            dst_conn.close()
        if keep > 0:
            for old in sorted(backup_dir.glob(f"{self.path.stem}-*.db"))[:-keep]:
                old.unlink(missing_ok=True)
        return dst

    def _auto_backup(self, reason: str) -> None:
        """Back up after a user-data change. Skipped for isolated/test DBs, and
        a failure here must never break the save that triggered it.
        """
        if os.getenv("TERMINAL_DB_PATH"):     # test/isolated DB — don't litter backups
            return
        from src.config import get_config

        cfg = get_config()
        if not cfg.get("app.auto_backup", True):
            return
        with contextlib.suppress(Exception):  # a backup must never break a save
            self.backup(keep=int(cfg.get("app.auto_backup_keep", 10)), reason=reason)

    def close(self) -> None:
        self.conn.close()


@lru_cache(maxsize=1)
def get_db() -> Database:
    return Database()
