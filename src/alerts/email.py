"""Email alerts (optional) via SMTP. No-op unless fully configured."""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from src.config import get_config
from src.utils.logging import get_logger, log_network_call

log = get_logger("email")


def configured() -> bool:
    cfg = get_config()
    return all(cfg.env(k) for k in (
        "ALERT_EMAIL_SMTP_HOST", "ALERT_EMAIL_USERNAME",
        "ALERT_EMAIL_PASSWORD", "ALERT_EMAIL_TO",
    ))


def send_email(subject: str, body: str) -> bool:
    cfg = get_config()
    if not configured() or not cfg.allow_network:
        log.info("Email not configured / network off — skipping.")
        return False
    host = cfg.env("ALERT_EMAIL_SMTP_HOST")
    port = int(cfg.env("ALERT_EMAIL_SMTP_PORT", "587") or 587)
    user = cfg.env("ALERT_EMAIL_USERNAME")
    pwd = cfg.env("ALERT_EMAIL_PASSWORD")
    to = cfg.env("ALERT_EMAIL_TO")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    try:
        log_network_call("email-smtp", f"smtp://{host}:{port}", method="SMTP")
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, [to], msg.as_string())
        return True
    except Exception as exc:  # pragma: no cover - network
        log.warning("Email send failed: %s", exc)
        return False
