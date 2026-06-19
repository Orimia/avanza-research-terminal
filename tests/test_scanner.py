"""Scanner integration (offline/mock): a scan runs and de-dups across runs."""
from src.engine.scanner import run_scan
from src.storage.db import get_db


def _clear_engine_state():
    db = get_db()
    db.conn.execute("DELETE FROM signal_state")
    db.conn.execute("DELETE FROM alerts_log")
    db.conn.commit()


def test_full_scan_runs_and_dedups_offline():
    _clear_engine_state()
    first = run_scan("manual", send=False)
    assert first.scanned > 0
    assert not first.errors
    # first run on fresh state should surface at least some actionable signals
    assert len(first.emitted) >= 1
    # an immediate second run must not re-fire any TRANSITION signal (new buy,
    # holding action, MA/RSI/breakout, earnings). Recurring 'big move' signals
    # that were capped out of run 1 may legitimately fire in run 2.
    second = run_scan("manual", send=False)
    transitions = [s for s in second.emitted if not s.recurring_daily]
    assert transitions == []
    assert len(second.emitted) <= len(first.emitted)


def test_intraday_scan_runs_offline():
    _clear_engine_state()
    res = run_scan("intraday", send=False)
    assert res.scanned > 0
    assert not res.errors
    # a scan run is recorded for engine health
    assert get_db().last_scan_run() is not None
