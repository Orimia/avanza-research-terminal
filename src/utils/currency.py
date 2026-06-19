"""Currency helpers — convert local-currency amounts to SEK base."""
from __future__ import annotations

CCY_FOR_EXCHANGE = {
    "ST": "SEK", "STO": "SEK", "OMX": "SEK",  # Stockholm
    "US": "USD", "NYSE": "USD", "NASDAQ": "USD",
    "EU": "EUR", "XETRA": "EUR", "PAR": "EUR", "AMS": "EUR", "MIL": "EUR",
    "CO": "DKK", "HE": "EUR", "OL": "NOK",
    "CC": "USD", "CRYPTO": "USD",            # crypto sleeve — priced in USD
}


def currency_for_exchange(exchange: str) -> str:
    return CCY_FOR_EXCHANGE.get((exchange or "").upper(), "SEK")


def fx_pair_key(ccy: str) -> str:
    """Map a currency to the FX dict key used in config (e.g. USD -> USDSEK)."""
    ccy = (ccy or "SEK").upper()
    return f"{ccy}SEK"


def to_sek(amount: float, ccy: str, fx_rates: dict[str, float]) -> float:
    """Convert ``amount`` in ``ccy`` to SEK using the rate map.

    ``fx_rates`` maps keys like 'USDSEK' -> SEK per 1 unit. SEK -> 1.0.
    Unknown currencies fall back to 1.0 (treated as SEK) — callers should make
    sure the rate exists; this is a safety net, not a silent guess for reports.
    """
    ccy = (ccy or "SEK").upper()
    if ccy == "SEK":
        return amount
    rate = fx_rates.get(fx_pair_key(ccy))
    if rate is None:
        return amount  # safety net; surfaced as missing FX elsewhere
    return amount * rate


def whole_shares(target_amount_sek: float, price_sek: float) -> int:
    """Whole-share count that does not exceed the SEK budget (never fractional)."""
    if price_sek <= 0:
        return 0
    return int(target_amount_sek // price_sek)
