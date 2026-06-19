"""Analyse the crypto sleeve (a separate account, e.g. Coinbase).

Kept entirely apart from the equity portfolio: coins are priced via Yahoo
``<SYM>-USD``, weighted WITHIN the crypto sleeve (so they never distort equity
concentration), and judged by the crypto model + thesis rules. Values display in
both USD (native) and SEK (base currency).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config import Config, get_config
from src.data.fx_client import get_fx_rates
from src.data.provider import get_stock_data, screen_data
from src.models.schemas import CryptoSignal
from src.scoring.crypto import build_crypto_signal, decide_crypto_holding, decide_crypto_new
from src.scoring.technicals import compute_technicals
from src.storage.db import get_db
from src.universe.crypto import crypto_screen_entries, name_of, tier_of
from src.utils.currency import to_sek


@dataclass
class CryptoAccountReview:
    signals: list[CryptoSignal] = field(default_factory=list)
    value_usd: float = 0.0
    value_sek: float = 0.0
    cost_usd: float = 0.0
    n_holdings: int = 0
    any_mock: bool = False

    @property
    def unrealized_pct(self) -> float | None:
        if self.cost_usd <= 0:
            return None
        return (self.value_usd - self.cost_usd) / self.cost_usd

    @property
    def actions(self) -> list[CryptoSignal]:
        """Holdings that need a non-HOLD action (the actual to-do list)."""
        return [s for s in self.signals if s.label and not s.label.startswith(("HOLD", "IGNORE"))]


def _btc_ret_3m(force_refresh: bool = False) -> float | None:
    try:
        btc = get_stock_data("BTC", "CC", force_refresh=force_refresh, enrich_news=False)
        return compute_technicals(btc).ret_3m
    except Exception:
        return None


def analyze_crypto_holdings(*, force_refresh: bool = False,
                            cfg: Config | None = None) -> CryptoAccountReview:
    cfg = cfg or get_config()
    fx = get_fx_rates()
    holdings = get_db().crypto_holdings_all()
    review = CryptoAccountReview(n_holdings=len(holdings))
    if not holdings:
        return review

    btc_3m = _btc_ret_3m(force_refresh)
    sigs: list[CryptoSignal] = []
    for h in holdings:
        data = get_stock_data(h.ticker, h.exchange, force_refresh=force_refresh, enrich_news=False)
        sig = build_crypto_signal(data, tier=tier_of(h.ticker), name=name_of(h.ticker),
                                  btc_ret_3m=btc_3m, cfg=cfg)
        price = sig.price or h.current_price
        sig.is_holding = True
        sig.qty = h.shares
        sig.staked_pct = h.staked_pct
        if price is not None:
            sig.value_usd = price * h.shares
            sig.unrealized_pct = (price / h.average_cost - 1.0) if h.average_cost else None
        review.value_usd += sig.value_usd or 0.0
        review.cost_usd += (h.average_cost * h.shares) if h.average_cost else 0.0
        review.any_mock = review.any_mock or sig.is_mock
        sigs.append(sig)

    tv = review.value_usd or 1.0
    for sig in sigs:
        sig.weight_pct = round((sig.value_usd or 0) / tv * 100, 1)
        sig.value_sek = to_sek(sig.value_usd or 0, "USD", fx)
        decide_crypto_holding(sig, cfg)
    sigs.sort(key=lambda s: s.value_usd or 0, reverse=True)
    review.signals = sigs
    review.value_sek = to_sek(review.value_usd, "USD", fx)
    return review


def run_crypto_discovery(*, limit: int | None = None, force_refresh: bool = False,
                         cfg: Config | None = None) -> list[CryptoSignal]:
    cfg = cfg or get_config()
    entries = crypto_screen_entries(limit)
    stocks = screen_data(entries) if not force_refresh else [
        get_stock_data(t, e, force_refresh=True, enrich_news=False) for t, e in entries]
    by_sym = {s.ticker.upper().replace("-USD", ""): s for s in stocks}
    btc = by_sym.get("BTC")
    btc_3m = compute_technicals(btc).ret_3m if btc else None
    held = {h.ticker.upper() for h in get_db().crypto_holdings_all()}

    out: list[CryptoSignal] = []
    for sym, _ in entries:
        data = by_sym.get(sym.upper())
        # skip coins with no real data — never rank synthetic/mock prices as
        # genuine discovery opportunities (holdings still show, flagged, in their view)
        if data is None or data.is_mock or not data.closes():
            continue
        sig = build_crypto_signal(data, tier=tier_of(sym), name=name_of(sym),
                                  btc_ret_3m=btc_3m, cfg=cfg)
        decide_crypto_new(sig, cfg)
        sig.is_holding = sym.upper() in held
        out.append(sig)
    out.sort(key=lambda s: s.composite, reverse=True)
    return out
