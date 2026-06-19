"""Crypto scoring + thesis-aware decisions.

Coins have no fundamentals, so this is a deliberately *separate* model from the
equity composite. Five components, all 0–100 (higher = better):

    trend         price vs MA50 / MA200 (structural up/down trend)
    momentum      3m/6m/12m returns + RSI
    quality_tier  BTC/ETH=1 · major L1=2 · speculative=3  (durability proxy)
    btc_relative  3-month return vs BTC (is it even beating the benchmark coin?)
    risk          volatility + downtrend penalty (higher = safer)

Decisions encode the user's thesis (set in config ``crypto``):
  * BTC is the ONLY sanctioned destination for new money; ETH secondary on a
    confirmed up-trend; tier-2/3 alts are never new-money buys (no edge).
  * Holdings: keep the core (BTC/ETH/SOL), never panic-sell quality at the lows,
    consolidate the speculative tail INTO BTC, ignore dust.
Research only — nothing here trades or automates anything.
"""
from __future__ import annotations

from src.config import Config, get_config
from src.models.schemas import Action, CryptoSignal, StockData
from src.scoring import clamp, lin, wavg
from src.scoring.technicals import compute_technicals

_TIER_QUALITY = {1: 92.0, 2: 64.0, 3: 40.0}
_TIER_RISK_NUDGE = {1: 8.0, 2: 0.0, 3: -8.0}


def _rsi_points(r: float | None) -> float | None:
    if r is None:
        return None
    if 45 <= r <= 65:
        return 85.0
    if r > 75:
        return 50.0      # extended
    if r < 30:
        return 35.0      # washed out / no demand
    return 65.0


def build_crypto_signal(data: StockData, *, tier: int, name: str,
                        btc_ret_3m: float | None, cfg: Config | None = None) -> CryptoSignal:
    """Score one coin. No action/label yet — that's the decision step."""
    cfg = cfg or get_config()
    t = compute_technicals(data)
    price = data.quote.price if data.quote else (data.closes()[-1] if data.closes() else None)

    pv50, pv200 = t.price_vs_ma50, t.price_vs_ma200
    trend = wavg([
        (lin(pv50, -0.15, 0.15, 25, 85), 0.5),
        (lin(pv200, -0.30, 0.30, 20, 92), 0.5),
    ])
    momentum = wavg([
        (lin(t.ret_1m, -0.20, 0.25, 25, 85), 0.15),
        (lin(t.ret_3m, -0.35, 0.45, 15, 92), 0.35),
        (lin(t.ret_6m, -0.50, 0.70, 15, 92), 0.25),
        (lin(t.ret_12m, -0.60, 1.20, 15, 92), 0.15),
        (_rsi_points(t.rsi14), 0.10),
    ])
    quality_tier = _TIER_QUALITY.get(tier, 40.0)
    btc_relative = None
    if btc_ret_3m is not None and t.ret_3m is not None:
        btc_relative = lin(t.ret_3m - btc_ret_3m, -0.30, 0.30, 20, 90)
    risk = lin(t.volatility, 1.30, 0.40, 20, 90)
    if risk is not None:
        risk += _TIER_RISK_NUDGE.get(tier, 0.0)
        if pv200 is not None and pv200 < -0.30:
            risk -= 10.0                      # deep, structural downtrend
        risk = clamp(risk)

    w = cfg.get("crypto.weights", {}) or {}
    composite = wavg([
        (trend, w.get("trend", 0.25)),
        (momentum, w.get("momentum", 0.20)),
        (quality_tier, w.get("quality_tier", 0.25)),
        (btc_relative, w.get("btc_relative", 0.15)),
        (risk, w.get("risk", 0.15)),
    ]) or 0.0

    dd = (price / t.wk52_high - 1.0) if (price and t.wk52_high) else None
    return CryptoSignal(
        symbol=data.ticker.upper().replace("-USD", ""), name=name, tier=tier,
        price=price, is_mock=data.is_mock,
        composite=round(clamp(composite), 1),
        trend=_r(trend), momentum=_r(momentum), quality_tier=_r(quality_tier),
        btc_relative=_r(btc_relative), risk=_r(risk),
        ret_3m=t.ret_3m, ret_6m=t.ret_6m, ret_12m=t.ret_12m,
        drawdown_from_high=dd, volatility=t.volatility, rsi=t.rsi14,
        above_ma50=(pv50 > 0) if pv50 is not None else None,
        above_ma200=(pv200 > 0) if pv200 is not None else None,
        rationale=_data_line(price, t, dd),
    )


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _data_line(price, t, dd) -> str:
    bits = []
    if t.ret_3m is not None:
        bits.append(f"3m {t.ret_3m * 100:+.0f}%")
    if t.ret_12m is not None:
        bits.append(f"12m {t.ret_12m * 100:+.0f}%")
    if dd is not None:
        bits.append(f"{dd * 100:+.0f}% from 1y high")
    if t.volatility is not None:
        bits.append(f"vol {t.volatility * 100:.0f}%")
    if t.rsi14 is not None:
        bits.append(f"RSI {t.rsi14:.0f}")
    if t.price_vs_ma200 is not None:
        bits.append("above 200-day" if t.price_vs_ma200 > 0 else "below 200-day")
    return " · ".join(bits)


def _risk_line(sig: CryptoSignal) -> str:
    flags = []
    if sig.tier == 3:
        flags.append("tier-3 speculative — most never reclaim prior highs")
    if sig.drawdown_from_high is not None and sig.drawdown_from_high < -0.6:
        flags.append(f"{sig.drawdown_from_high * 100:.0f}% below its high (deep)")
    if sig.volatility is not None and sig.volatility > 0.9:
        flags.append(f"very high volatility ({sig.volatility * 100:.0f}%)")
    if sig.above_ma200 is False:
        flags.append("in a downtrend (below 200-day)")
    return "; ".join(flags) if flags else "broad crypto-market beta; sector risk-off hits everything"


# --------------------------------------------------------------------------- #
# Discovery decision (thesis-aware: BTC-only new money)
# --------------------------------------------------------------------------- #
def decide_crypto_new(sig: CryptoSignal, cfg: Config | None = None) -> CryptoSignal:
    cfg = cfg or get_config()
    new_money = str(cfg.get("crypto.new_money_symbol", "BTC")).upper()
    eth_secondary = bool(cfg.get("crypto.accumulate_tier1_secondary", True))
    comp = sig.composite
    constructive = (sig.trend or 0) >= 55 or sig.above_ma50 is True
    strong_trend = sig.above_ma200 is True and (sig.momentum or 0) >= 55

    if sig.symbol == new_money:
        if constructive:
            sig.action, sig.label = Action.BUY, "ACCUMULATE"
            sig.headline = "The one coin worth new money — accumulate / DCA into strength."
        else:
            sig.action, sig.label = Action.HOLD, "DCA target"
            sig.headline = ("Still the destination for any new crypto money, but the trend "
                            "is down — DCA slowly, don't chase.")
    elif sig.tier == 1 and eth_secondary and strong_trend:
        sig.action, sig.label = Action.BUY, "ACCUMULATE (secondary)"
        sig.headline = "Tier-1 and the trend is turning up — the only alt worth fresh capital after BTC."
    elif sig.tier == 1:
        sig.action, sig.label = Action.WATCH, "HOLD / wait"
        sig.headline = "Tier-1, but the up-trend isn't confirmed — accumulate only on strength, not here."
    else:
        # tier 2/3 — never a new-money buy under the thesis, however it screens
        if comp < 42:
            sig.action, sig.label = Action.AVOID, "AVOID"
            sig.headline = "Weak across the board — nothing here."
        elif comp >= 60 and (sig.momentum or 0) >= 60:
            sig.action, sig.label = Action.WATCH, "WATCH (no new alt buys)"
            sig.headline = (f"Screens well ({comp:.0f}) on momentum — but your thesis is no new alt "
                            "bets, and you have no edge here. Track it, don't buy it.")
        else:
            sig.action, sig.label = Action.WATCH, "WATCH"
            sig.headline = "Middling — not a new-money candidate under a BTC-only rule."
    sig.biggest_risk = _risk_line(sig)
    return sig


# --------------------------------------------------------------------------- #
# Holding decision (thesis-aware: keep core, consolidate tail → BTC, ignore dust)
# --------------------------------------------------------------------------- #
def decide_crypto_holding(sig: CryptoSignal, cfg: Config | None = None) -> CryptoSignal:
    cfg = cfg or get_config()
    core = {str(s).upper() for s in (cfg.get("crypto.core", ["BTC", "ETH", "SOL"]) or [])}
    new_money = str(cfg.get("crypto.new_money_symbol", "BTC")).upper()
    dust_below = float(cfg.get("crypto.dust_usd_below", 15))
    cap = float(cfg.get("crypto.single_name_cap_pct", 0.55)) * 100

    val = sig.value_usd or 0.0
    is_dust = 0 < val < dust_below
    is_core = sig.symbol in core
    over_cap = sig.weight_pct is not None and sig.weight_pct > cap

    sig.flags = []
    if is_core:
        sig.flags.append("core")
    if is_dust:
        sig.flags.append("dust")
    if sig.staked_pct:
        sig.flags.append("staked")
    if over_cap:
        sig.flags.append("concentration")

    if is_dust:
        sig.action, sig.label = Action.HOLD, "IGNORE (dust)"
        sig.headline = (f"${val:.2f} — immaterial. A sale costs more in spread/fees than it's "
                        "worth; leave it, or clear it in one tap to tidy the list.")
        sig.trade_note = "Leave it (dust)"
    elif is_core and sig.symbol == new_money:
        sig.action, sig.label = Action.HOLD, "HOLD — core"
        sig.headline = ("Your highest-quality coin and the home for any new crypto money. "
                        "Hold; add here, not in the alts.")
        if over_cap:
            sig.headline += f" It's {sig.weight_pct:.0f}% of the sleeve — fine for BTC, just don't over-add."
        sig.trade_note = "Hold — no change"
    elif is_core:
        sig.action, sig.label = Action.HOLD, "HOLD — core"
        if over_cap:
            sig.headline = (f"Core hold — don't sell quality at the lows. But it's {sig.weight_pct:.0f}% "
                            "of your crypto: large single-name, so don't add to it.")
        else:
            sig.headline = "Core hold. Beaten down, but don't sell quality at the lows."
        sig.trade_note = "Hold — no change"
    else:
        deep_weak = sig.tier == 3 or (sig.composite or 50) < 45
        sig.action = Action.SELL if deep_weak else Action.TRIM
        sig.label = "SELL → BTC" if deep_weak else "TRIM → BTC"
        sig.headline = ("Speculative tail, not core — consolidate into BTC. You have no edge "
                        "holding this, and it bled across the cycle.")
        qty = sig.qty or 0
        verb = "Sell" if deep_weak else "Trim"
        note = f"{verb} ~{qty:g} {sig.symbol} (~${val:.0f}) → BTC"
        if sig.staked_pct:
            note += " · unstake first (cooldown)"
        sig.trade_note = note

    if sig.action in (Action.SELL, Action.TRIM) and sig.staked_pct:
        sig.headline += f" Note: {sig.staked_pct:.0f}% staked — unstake first (cooldown of days)."
    sig.biggest_risk = _risk_line(sig)
    return sig
