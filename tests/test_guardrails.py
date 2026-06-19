"""Hard guardrails: the codebase must contain NO broker automation.

These tests are intentionally strict. They scan the source tree to ensure no
module ever logs into Avanza, places orders, or stores broker credentials.
"""

from src.config import PROJECT_ROOT, get_config

SRC = PROJECT_ROOT / "src"

# Code-level identifiers that would indicate broker automation / credential
# capture. These are snake_case symbols that never appear in prose disclaimers
# (which legitimately say things like "no Avanza login"), so matching them
# catches real order-execution / credential code without false positives.
FORBIDDEN = [
    "place_order", "placeorder", "submit_order", "send_order", "place_trade",
    "execute_trade", "execute_order", "place_buy_order", "place_sell_order",
    "broker_password", "broker_username", "avanza_username", "avanza_password",
    "totp_avanza", "store_broker_credentials(",
]


def _source_files():
    return list(SRC.rglob("*.py"))


def test_no_broker_automation_terms_in_source():
    offenders = {}
    for path in _source_files():
        text = path.read_text(encoding="utf-8").lower()
        hits = [p for p in FORBIDDEN if p in text]
        if hits:
            offenders[str(path)] = hits
    assert not offenders, f"Forbidden broker-automation terms found: {offenders}"


def test_guardrail_flags_are_off():
    cfg = get_config()
    g = cfg.get("app.guardrails", {})
    assert g.get("broker_login") is False
    assert g.get("place_orders") is False
    assert g.get("store_broker_credentials") is False
    assert g.get("options_enabled") is False
    assert g.get("certificates_enabled") is False
    assert g.get("whole_shares_only") is True


def test_env_example_does_not_request_avanza_credentials():
    """Check declared env *variables* (not prose) never request broker creds."""
    lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    var_names = [
        line.split("=", 1)[0].strip().upper()
        for line in lines
        if "=" in line and not line.strip().startswith("#")
    ]
    forbidden_fragments = ("AVANZA", "BANKID", "BROKER_PASSWORD", "BROKER_USERNAME", "_PIN")
    bad = [v for v in var_names if any(f in v for f in forbidden_fragments)]
    assert not bad, f"Forbidden credential variables declared in .env.example: {bad}"
