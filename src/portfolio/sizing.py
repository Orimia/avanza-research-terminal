"""Risk-aware position sizing in SEK with whole-share counts."""
from __future__ import annotations

from src.config import Config, get_config
from src.models.schemas import Action, PositionSizing, ScoreBreakdown
from src.scoring import clamp
from src.utils.currency import to_sek, whole_shares


def suggest_weight(action: Action, b: ScoreBreakdown, *, high_risk: bool,
                   cfg: Config | None = None) -> float:
    """Suggested target weight as a fraction of portfolio (e.g. 0.05)."""
    cfg = cfg or get_config()
    max_new = float(cfg.get("risk.max_new_position_pct", 0.05))
    max_hr = float(cfg.get("risk.max_high_risk_position_pct", 0.02))
    cap = max_hr if high_risk else max_new
    if action == Action.AVOID:
        return 0.0
    # conviction factor from composite (50 -> 0.2x, 80+ -> 1.0x)
    factor = clamp((b.composite - 50.0) / 30.0, 0.2, 1.0) / 1.0
    if action == Action.WATCH:
        factor *= 0.5
    return round(cap * factor, 4)


def size_position(price_local: float, currency: str, fx: dict[str, float],
                  portfolio_value_sek: float, target_weight: float, *,
                  avg_turnover_local: float | None = None, high_risk: bool = False,
                  cfg: Config | None = None) -> PositionSizing:
    cfg = cfg or get_config()
    fx_rate = fx.get(f"{currency.upper()}SEK", 1.0 if currency.upper() == "SEK" else None)
    if fx_rate is None:
        fx_rate = 1.0  # safety net; flagged via currency_risk note below
    price_sek = price_local * fx_rate

    # enforce hard caps
    max_new = float(cfg.get("risk.max_new_position_pct", 0.05))
    max_hr = float(cfg.get("risk.max_high_risk_position_pct", 0.02))
    cap = max_hr if high_risk else max_new
    target_weight = min(target_weight, cap)

    target_sek = portfolio_value_sek * target_weight
    shares = whole_shares(target_sek, price_sek)
    actual_sek = shares * price_sek
    actual_weight = actual_sek / portfolio_value_sek if portfolio_value_sek else 0.0

    liquidity_warning = None
    if avg_turnover_local:
        turnover_sek = to_sek(avg_turnover_local, currency, fx)
        warn_frac = float(cfg.get("risk.position_vs_adv_warn", 0.10))
        if turnover_sek > 0 and target_sek > warn_frac * turnover_sek:
            liquidity_warning = (
                f"Order ~{target_sek/1e3:.0f} kSEK is "
                f"{target_sek/turnover_sek*100:.0f}% of avg daily turnover — split over days."
            )

    currency_risk = None
    if currency.upper() != "SEK":
        currency_risk = f"{currency.upper()} exposure — FX moves affect SEK value (rate {fx_rate:.2f})."

    return PositionSizing(
        currency=currency.upper(), price_local=round(price_local, 2), fx_to_sek=round(fx_rate, 4),
        price_sek=round(price_sek, 2), target_weight_pct=round(target_weight * 100, 2),
        target_sek=round(target_sek), shares=shares, actual_sek=round(actual_sek),
        actual_weight_pct=round(actual_weight * 100, 2),
        risk_bucket="high-risk" if high_risk else "normal",
        liquidity_warning=liquidity_warning, currency_risk=currency_risk,
    )
