"""Telegram alerts (optional).

Sends a message via the Bot API only if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
are set and network is allowed. Never sends silently — the call is logged.
"""
from __future__ import annotations

from src.config import get_config
from src.models.schemas import Recommendation
from src.utils.logging import get_logger, log_network_call

log = get_logger("telegram")


def configured() -> bool:
    cfg = get_config()
    return bool(cfg.env("TELEGRAM_BOT_TOKEN") and cfg.env("TELEGRAM_CHAT_ID"))


def format_daily(recs: list[Recommendation]) -> str:
    buys = [r for r in recs if r.action.value == "BUY"][:5]
    lines = ["📈 Daily research digest (not financial advice)"]
    if not buys:
        lines.append("No BUY-rated names today.")
    for r in buys:
        lines.append(f"• {r.action.value} {r.symbol} — score {r.score.composite:.0f}, "
                     f"{r.confidence.value} conf")
    return "\n".join(lines)


def resolve_chat_ids() -> list[dict]:
    """Call getUpdates and return distinct chats that have messaged the bot.

    Helps the user find their TELEGRAM_CHAT_ID: DM the bot once, then run this.
    """
    cfg = get_config()
    token = cfg.env("TELEGRAM_BOT_TOKEN")
    if not token or not cfg.allow_network:
        return []
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        import httpx

        log_network_call("telegram", "https://api.telegram.org/bot***/getUpdates")
        resp = httpx.get(url, timeout=10.0)
        seen: dict[int, dict] = {}
        for upd in resp.json().get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat", {})
            cid = chat.get("id")
            if cid is not None and cid not in seen:
                seen[cid] = {"id": cid,
                             "name": chat.get("title") or chat.get("username")
                             or chat.get("first_name") or "(chat)"}
        return list(seen.values())
    except Exception as exc:  # pragma: no cover - network
        log.warning("getUpdates failed: %s", exc)
        return []


def send_test() -> bool:
    return send_telegram("✅ Avanza Research Terminal connected — you'll receive "
                         "BUY/TRIM/SELL alerts here. (Research only; not financial advice.)")


def send_telegram(text: str) -> bool:
    cfg = get_config()
    if not configured() or not cfg.allow_network:
        log.info("Telegram not configured / network off — skipping.")
        return False
    token = cfg.env("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.env("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import httpx

        log_network_call("telegram", "https://api.telegram.org/bot***/sendMessage", method="POST")
        resp = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
        log_network_call("telegram", "https://api.telegram.org/bot***/sendMessage",
                         method="POST", status=resp.status_code)
        return resp.status_code == 200
    except Exception as exc:  # pragma: no cover - network
        log.warning("Telegram send failed: %s", exc)
        return False


if __name__ == "__main__":  # python -m src.alerts.telegram  -> list chat ids
    chats = resolve_chat_ids()
    if not chats:
        print("No chats found. DM your bot once, then re-run. "
              "(Is TELEGRAM_BOT_TOKEN set in .env and ALLOW_NETWORK=true?)")
    else:
        print("Chats that have messaged your bot (use the id as TELEGRAM_CHAT_ID):")
        for c in chats:
            print(f"  {c['id']}  —  {c['name']}")
