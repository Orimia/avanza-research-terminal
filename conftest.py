"""Pytest bootstrap: importable ``src.*`` + force offline, deterministic tests."""
import os
import sys
import tempfile

# Force fully offline mode so tests never hit the network and always use the
# deterministic mock data path. Must be set before any src import.
os.environ.setdefault("ALLOW_NETWORK", "false")

# Isolate the SQLite cache in a fresh temp DB so tests never read a user's real
# (possibly live) cached data — guarantees the mock-fallback path is exercised.
if "TERMINAL_DB_PATH" not in os.environ:
    _test_db = os.path.join(tempfile.gettempdir(), "art_test_terminal.db")
    os.environ["TERMINAL_DB_PATH"] = _test_db
    try:
        if os.path.exists(_test_db):
            os.remove(_test_db)
    except OSError:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
