"""Optional alert channels (Telegram, email). No-ops unless configured."""
from src.alerts.email import send_email  # noqa: F401
from src.alerts.telegram import send_telegram  # noqa: F401
