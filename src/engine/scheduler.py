"""Always-on engine entrypoint.

Usage:
    python -m src.engine.scheduler            # run forever (daemon)
    python -m src.engine.scheduler once       # single full scan + send (cron-style)
    python -m src.engine.scheduler intraday   # single intraday scan + send
    python -m src.engine.scheduler dry-run    # full scan, print message, send nothing

The daemon runs an intraday scan every ``engine.scan_interval_minutes`` (gated to
market hours) plus a morning and post-close digest at the configured local times.
"""
from __future__ import annotations

import sys
from zoneinfo import ZoneInfo

from src.config import get_config
from src.engine.market_hours import any_market_open
from src.engine.scanner import run_scan
from src.utils.logging import get_logger, setup_logging

log = get_logger("engine.scheduler")


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = str(value).split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return default


def _intraday_job() -> None:
    cfg = get_config()
    scope = cfg.get("engine.scope", ["nordic", "eu", "us"])
    if cfg.get("engine.market_hours_only", True) and not any_market_open(scope):
        log.debug("All markets closed — skipping intraday scan.")
        return
    res = run_scan("intraday")
    log.info("intraday: scanned=%d emitted=%d", res.scanned, len(res.emitted))


def _pulse_job() -> None:
    cfg = get_config()
    scope = cfg.get("engine.scope", ["nordic", "eu", "us"])
    if cfg.get("engine.market_hours_only", True) and not any_market_open(scope):
        return
    from src.engine.scanner import run_portfolio_pulse

    res = run_portfolio_pulse()
    log.info("pulse: %d holdings, %d actions", res.n_holdings, len(res.actions))


def run() -> None:
    setup_logging()
    cfg = get_config()
    if not cfg.get("engine.enabled", True):
        log.warning("engine.enabled is false — not starting scheduler.")
        return

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    tz = ZoneInfo(cfg.get("engine.timezone", "Europe/Stockholm"))
    sched = BlockingScheduler(timezone=tz)
    interval = int(cfg.get("engine.scan_interval_minutes", 20))
    mh = _parse_hhmm(cfg.get("engine.morning_digest", "08:15"), (8, 15))
    ch = _parse_hhmm(cfg.get("engine.close_digest", "22:15"), (22, 15))

    sched.add_job(_intraday_job, IntervalTrigger(minutes=interval),
                  id="intraday", max_instances=1, coalesce=True)
    sched.add_job(lambda: run_scan("morning"),
                  CronTrigger(hour=mh[0], minute=mh[1], day_of_week="mon-fri"),
                  id="morning", max_instances=1)
    sched.add_job(lambda: run_scan("close"),
                  CronTrigger(hour=ch[0], minute=ch[1], day_of_week="mon-fri"),
                  id="close", max_instances=1)
    if cfg.get("engine.portfolio_pulse_enabled", True):
        pulse_h = int(cfg.get("engine.portfolio_pulse_hours", 3))
        sched.add_job(_pulse_job, IntervalTrigger(hours=pulse_h),
                      id="pulse", max_instances=1, coalesce=True)
        log.info("portfolio pulse every %dh (market hours)", pulse_h)

    log.info("Engine started — intraday every %dm (market hours), "
             "morning %02d:%02d, close %02d:%02d %s",
             interval, mh[0], mh[1], ch[0], ch[1], tz.key)
    # immediate startup digest so you get instant confirmation it's live
    try:
        run_scan("manual")
    except Exception:  # pragma: no cover - defensive
        log.exception("startup scan failed")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover
        log.info("Engine stopped.")


def main(argv: list[str]) -> None:
    setup_logging()
    mode = argv[1] if len(argv) > 1 else "daemon"
    if mode in ("once", "full", "manual"):
        res = run_scan("manual")
        print(f"full scan: scanned={res.scanned} emitted={len(res.emitted)} "
              f"top_buys={len(res.top_buys)}")
    elif mode == "intraday":
        res = run_scan("intraday")
        print(f"intraday scan: scanned={res.scanned} emitted={len(res.emitted)}")
    elif mode in ("dry-run", "dryrun", "preview"):
        from src.engine.notify import preview_text

        res = run_scan("manual", send=False)
        print(preview_text(res))
    elif mode in ("test-alert", "test"):
        from src.engine.notify import send_test

        ok = send_test()
        print("✅ test alert sent" if ok else
              "⚠️ not sent — configure TELEGRAM_*/ALERT_EMAIL_* in .env and channels in config.yaml")
    elif mode == "pulse":
        from src.engine.scanner import run_portfolio_pulse

        res = run_portfolio_pulse()
        print(f"pulse sent: {res.n_holdings} holdings, {len(res.actions)} actions")
    elif mode in ("pulse-dry", "pulse-preview"):
        from src.engine.notify import format_pulse
        from src.engine.scanner import run_portfolio_pulse

        res = run_portfolio_pulse(send=False)
        print(format_pulse(res)[1])
    else:
        run()


if __name__ == "__main__":
    main(sys.argv)
