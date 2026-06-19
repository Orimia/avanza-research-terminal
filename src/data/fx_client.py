"""FX rates (USD/SEK, EUR/SEK, ...).

Defaults to static rates from config so the app works fully offline. If
``FX_API_KEY`` is set and network is allowed, it may fetch live rates — and
logs every call to the network audit log. Live fetch failure silently falls
back to static (logged).
"""
from __future__ import annotations

from functools import lru_cache

from src.config import get_config
from src.utils.logging import get_logger, log_network_call

log = get_logger("fx")


def _static_rates() -> dict[str, float]:
    cfg = get_config()
    rates = dict(cfg.get("data.fx.static", {}) or {})
    rates.setdefault("SEKSEK", 1.0)
    return rates


def _fetch_live() -> dict[str, float] | None:
    """Best-effort live FX via exchangerate.host (no key needed for base call).

    Symbols are derived from the configured static table so adding a currency
    there automatically extends the live fetch. Fully logged; returns None on
    any problem (caller falls back to static rates).
    """
    cfg = get_config()
    if not cfg.allow_network:
        return None
    currencies = [k[:3] for k in _static_rates() if k.endswith("SEK") and k != "SEKSEK"]
    if not currencies:
        return None
    try:
        import httpx

        symbols = ",".join(sorted(set(currencies)))
        url = f"https://api.exchangerate.host/latest?base=SEK&symbols={symbols}"
        log_network_call("exchangerate.host", url, note="FX latest")
        resp = httpx.get(url, timeout=8.0)
        log_network_call("exchangerate.host", url, status=resp.status_code, note="FX latest done")
        rates = resp.json().get("rates", {})
        out = {"SEKSEK": 1.0}
        # API returns SEK->CCY; we want CCY->SEK = 1 / (SEK->CCY)
        for ccy in currencies:
            val = rates.get(ccy)
            if val:
                out[f"{ccy}SEK"] = round(1.0 / float(val), 4)
        if len(out) > 1:
            return out
    except Exception as exc:  # pragma: no cover - network optional
        log.warning("Live FX failed, using static rates: %s", exc)
    return None


@lru_cache(maxsize=1)
def get_fx_rates() -> dict[str, float]:
    """Return FX map like {'USDSEK': 10.55, 'EURSEK': 11.30, 'SEKSEK': 1.0}."""
    rates = _static_rates()
    cfg = get_config()
    if cfg.has_key("FX_API_KEY") or cfg.allow_network:
        live = _fetch_live()
        if live:
            rates.update(live)
            log.info("Using live FX rates: %s", live)
            return rates
    log.info("Using static FX rates: %s", rates)
    return rates


def clear_fx_cache() -> None:
    get_fx_rates.cache_clear()
