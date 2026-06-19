"""Logging setup, including an explicit audit log for outbound network calls.

A core product constraint is: *no hidden network calls*. Every real HTTP
request a data client makes should be routed through :func:`log_network_call`,
which appends a JSON line to ``logs/network.jsonl`` and emits a log record.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.config import PROJECT_ROOT, get_config

_LOG_DIR = PROJECT_ROOT / "logs"
_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _LOG_DIR.mkdir(exist_ok=True)
    cfg = get_config()
    level = getattr(logging, str(cfg.get("logging.level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8"),
        ],
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_network_call(provider: str, url: str, method: str = "GET",
                     status: int | None = None, note: str = "") -> None:
    """Record an outbound network call to the audit log.

    Call this for EVERY real request to a data provider so the user can always
    see what left the machine.
    """
    cfg = get_config()
    if not cfg.get("logging.log_network_calls", True):
        return
    _LOG_DIR.mkdir(exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "method": method,
        "url": url,
        "status": status,
        "note": note,
    }
    with open(_LOG_DIR / "network.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    get_logger("network").info("%s %s %s -> %s %s", provider, method, url, status, note)


def read_network_log(limit: int = 200) -> list[dict]:
    path = _LOG_DIR / "network.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
