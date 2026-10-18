"""Market-regime engine: classify the tape, adapt decision thresholds.

Reads a small set of index benchmarks (keyless via Yahoo; ``^GSPC``, ``^OMX``)
and classifies the regime from three deterministic components per index:

    trend      price vs its 200-day MA
    momentum   3-month return
    volatility 1-month realised vol vs its 1-year norm

The label is ALWAYS surfaced in the UI/digests, and (when
``regime.adapt_thresholds``) the BUY bar moves with it: harder in risk-off,
slightly easier in risk-on. Adjustments are explicit and bounded — no silent
behaviour changes, no forecasts, just "what kind of tape is this?".
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.config import Config, get_config
from src.models.schemas import StockData
from src.scoring.technicals import compute_technicals

RISK_ON = "risk-on"
NEUTRAL = "neutral"
RISK_OFF = "risk-off"
UNKNOWN = "unknown"


@dataclass
class RegimeState:
    label: str = UNKNOWN
    score: float = 0.0                       # -100 (max risk-off) .. +100
    components: dict = field(default_factory=dict)   # per-benchmark detail
    buy_min_effective: float | None = None   # filled by apply_regime
    as_of: str = ""
    note: str = ""

    @property
    def is_known(self) -> bool:
        return self.label != UNKNOWN


def _vol_ratio(closes: list[float]) -> float | None:
    """1-month realised vol vs 1-year baseline (>1 = hotter than normal)."""
    if len(closes) < 80:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    if len(rets) < 60:
        return None

    def sd(xs: list[float]) -> float:
        m = sum(xs) / len(xs)
        return (sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)) ** 0.5

    short, long = sd(rets[-21:]), sd(rets[-252:])
    return (short / long) if long > 0 else None


def classify(benchmarks: list[StockData]) -> RegimeState:
    """Pure classification from benchmark data (testable offline)."""
    real = [b for b in benchmarks if b is not None and not b.is_mock and len(b.closes()) >= 80]
    if not real:
        return RegimeState(label=UNKNOWN, note="no live benchmark data (offline?)",
                           as_of=datetime.now(timezone.utc).isoformat())
    total, per = 0.0, {}
    for b in real:
        t = compute_technicals(b)
        closes = b.closes()
        trend = 0 if t.price_vs_ma200 is None else (1 if t.price_vs_ma200 > 0 else -1)
        mom = 0
        if t.ret_3m is not None:
            mom = 1 if t.ret_3m > 0.02 else (-1 if t.ret_3m < -0.05 else 0)
        vr = _vol_ratio(closes)
        vol = 0 if vr is None else (1 if vr < 0.85 else (-1 if vr > 1.35 else 0))
        pts = trend + mom + vol
        total += pts
        per[b.ticker] = {"trend": trend, "momentum": mom, "vol": vol,
                         "ret_3m": t.ret_3m, "vs_ma200": t.price_vs_ma200,
                         "vol_ratio": round(vr, 2) if vr is not None else None}
    score = total / (3 * len(real)) * 100.0
    label = RISK_ON if score >= 25 else (RISK_OFF if score <= -25 else NEUTRAL)
    return RegimeState(label=label, score=round(score, 1), components=per,
                       as_of=datetime.now(timezone.utc).isoformat())


# module-level cache so the engine doesn't refetch benchmarks every scan
_CACHE: dict = {"state": None, "ts": 0.0}
_TTL_S = 900.0


def current_regime(*, force_refresh: bool = False, cfg: Config | None = None) -> RegimeState:
    """Fetch benchmarks (cached 15 min) and classify. Degrades to UNKNOWN offline."""
    cfg = cfg or get_config()
    if not cfg.get("regime.enabled", True):
        return RegimeState(label=UNKNOWN, note="regime engine disabled")
    now = datetime.now(timezone.utc).timestamp()
    if not force_refresh and _CACHE["state"] is not None and now - _CACHE["ts"] < _TTL_S:
        return _CACHE["state"]
    from src.data.provider import get_stock_data

    data = []
    for sym in cfg.get("regime.benchmarks", ["^GSPC", "^OMX"]) or []:
        try:
            data.append(get_stock_data(str(sym), "US", enrich_news=False))
        except Exception:  # pragma: no cover - defensive
            continue
    state = classify(data)
    _CACHE["state"], _CACHE["ts"] = state, now
    return state


def apply_regime(cfg: Config, state: RegimeState) -> tuple[Config, str]:
    """Return a threshold-adjusted copy of the config plus a one-line note.

    risk-off  -> buy_min_composite += risk_off_buy_bump (also the engine's
                 NEW_BUY alert bar); risk-on -> small relief. Neutral/unknown
                 -> unchanged. The original config is never mutated.
    """
    base_buy = float(cfg.get("decisions.buy_min_composite", 68))
    if not state.is_known or not cfg.get("regime.adapt_thresholds", True):
        state.buy_min_effective = base_buy
        return cfg, (f"Regime {state.label} — thresholds unchanged (BUY bar {base_buy:.0f})")
    bump = float(cfg.get("regime.risk_off_buy_bump", 6))
    relief = float(cfg.get("regime.risk_on_buy_relief", 2))
    delta = bump if state.label == RISK_OFF else (-relief if state.label == RISK_ON else 0.0)
    if delta == 0.0:
        state.buy_min_effective = base_buy
        return cfg, f"Regime {state.label} ({state.score:+.0f}) — BUY bar {base_buy:.0f}"
    data = copy.deepcopy(cfg.raw)
    data.setdefault("decisions", {})["buy_min_composite"] = base_buy + delta
    data.setdefault("engine", {}).setdefault("alerts", {})["new_buy_min_composite"] = (
        float(cfg.get("engine.alerts.new_buy_min_composite", base_buy)) + delta)
    state.buy_min_effective = base_buy + delta
    note = (f"Regime {state.label} ({state.score:+.0f}) — BUY bar "
            f"{base_buy:.0f}→{base_buy + delta:.0f}")
    return Config(data), note
