"""Typed schemas for the whole pipeline.

Design rule: *unavailable data is ``None``, never invented.* Optional fields
are how we mark "missing"; scoring and reports must treat ``None`` as missing
and lower confidence / coverage accordingly.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Action(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    TRIM = "TRIM"
    SELL = "SELL"
    AVOID = "AVOID"
    WATCH = "WATCH"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


# --------------------------------------------------------------------------- #
# Raw data
# --------------------------------------------------------------------------- #
class PriceBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Quote(BaseModel):
    price: float
    currency: str
    market_cap: Optional[float] = None        # local currency
    volume: Optional[float] = None             # latest-day share volume
    avg_volume: Optional[float] = None         # avg daily share volume
    avg_turnover: Optional[float] = None       # avg daily traded value, local ccy
    as_of: Optional[datetime] = None


class Fundamentals(BaseModel):
    # growth (fractions: 0.15 == 15%)
    revenue_growth: Optional[float] = None
    eps_growth: Optional[float] = None
    # profitability
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf: Optional[float] = None
    fcf_margin: Optional[float] = None
    roic: Optional[float] = None
    roe: Optional[float] = None
    # balance sheet
    cash: Optional[float] = None
    debt: Optional[float] = None
    net_debt_ebitda: Optional[float] = None
    # valuation
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ev_sales: Optional[float] = None
    ps: Optional[float] = None
    pb: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    as_of: Optional[date] = None

    def available_fields(self) -> int:
        return sum(1 for v in self.model_dump().values() if v is not None)


class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    timestamp: datetime
    summary: Optional[str] = None
    sentiment: Optional[float] = None          # -1..1 if known


class Catalysts(BaseModel):
    next_earnings_date: Optional[date] = None
    days_to_earnings: Optional[int] = None
    recent_guidance: Optional[str] = None
    analyst_revision_trend: Optional[float] = None   # -1..1
    insider_net_buying: Optional[float] = None       # + buying / - selling
    buyback_active: Optional[bool] = None
    dilution_risk: Optional[bool] = None
    short_interest_pct: Optional[float] = None


class AnalystView(BaseModel):
    """Sell-side analyst consensus (e.g. from Yahoo) — ~12-month horizon."""
    target_mean: Optional[float] = None
    target_high: Optional[float] = None
    target_low: Optional[float] = None
    n_analysts: Optional[int] = None
    recommendation: Optional[str] = None        # 'buy' / 'hold' / 'sell' ...
    recommendation_mean: Optional[float] = None  # 1=strong buy .. 5=strong sell

    def upside(self, price: float | None) -> Optional[float]:
        if self.target_mean is None or not price:
            return None
        return self.target_mean / price - 1.0


class SourceCoverage(BaseModel):
    provider: str = "mock"
    price: bool = False
    fundamentals: bool = False
    news: bool = False
    catalysts: bool = False
    is_mock: bool = True

    @property
    def quality(self) -> str:
        score = sum([self.price, self.fundamentals, self.news, self.catalysts])
        if self.is_mock:
            return "Mock"
        if score >= 4:
            return "Good"
        if score >= 2:
            return "Partial"
        return "Weak"


class StockData(BaseModel):
    ticker: str
    exchange: str
    name: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    currency: str = "SEK"
    quote: Optional[Quote] = None
    fundamentals: Optional[Fundamentals] = None
    price_history: list[PriceBar] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    catalysts: Optional[Catalysts] = None
    analyst: Optional[AnalystView] = None
    sources: list[str] = Field(default_factory=list)
    coverage: SourceCoverage = Field(default_factory=SourceCoverage)
    is_mock: bool = False
    fetched_at: Optional[datetime] = None

    @property
    def symbol(self) -> str:
        return f"{self.ticker}.{self.exchange}"

    @property
    def display_name(self) -> str:
        return self.name or self.ticker.upper()

    def closes(self) -> list[float]:
        return [b.close for b in self.price_history]


# --------------------------------------------------------------------------- #
# Derived analytics
# --------------------------------------------------------------------------- #
class TechnicalSnapshot(BaseModel):
    ret_1m: Optional[float] = None
    ret_3m: Optional[float] = None
    ret_6m: Optional[float] = None
    ret_12m: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    price_vs_ma50: Optional[float] = None
    price_vs_ma200: Optional[float] = None
    rsi14: Optional[float] = None
    rel_strength: Optional[float] = None         # vs local index proxy
    volume_anomaly: Optional[float] = None       # latest vol / avg vol
    support: Optional[float] = None
    resistance: Optional[float] = None
    volatility: Optional[float] = None           # annualised stdev
    wk52_high: Optional[float] = None
    wk52_low: Optional[float] = None
    pct_in_range: Optional[float] = None         # 0=at 52w low, 1=at 52w high


class ScoreBreakdown(BaseModel):
    quality: Optional[float] = None
    growth: Optional[float] = None
    valuation: Optional[float] = None
    momentum: Optional[float] = None
    catalyst: Optional[float] = None
    risk: Optional[float] = None
    liquidity: Optional[float] = None
    composite: float = 0.0
    coverage: float = 0.0    # fraction of weighted sub-scores that had data

    def as_dict(self) -> dict[str, Optional[float]]:
        return {
            "Quality": self.quality, "Growth": self.growth,
            "Valuation": self.valuation, "Momentum": self.momentum,
            "Catalyst": self.catalyst, "Risk": self.risk,
            "Liquidity": self.liquidity,
        }


class RiskReward(BaseModel):
    entry: float
    stop_loss: float
    take_profit: float
    upside_pct: float
    downside_pct: float
    rr_ratio: float


class PositionSizing(BaseModel):
    currency: str
    price_local: float
    fx_to_sek: float
    price_sek: float
    target_weight_pct: float
    target_sek: float
    shares: int
    actual_sek: float
    actual_weight_pct: float
    risk_bucket: str = "normal"        # normal / high-risk
    liquidity_warning: Optional[str] = None
    currency_risk: Optional[str] = None


class Recommendation(BaseModel):
    ticker: str
    exchange: str
    name: Optional[str] = None
    action: Action
    confidence: Confidence
    one_liner: str
    main_reason: str
    biggest_risk: str
    score: ScoreBreakdown
    technicals: Optional[TechnicalSnapshot] = None
    risk_reward: Optional[RiskReward] = None
    analyst: Optional[AnalystView] = None
    sizing: Optional[PositionSizing] = None
    data_freshness: str = "Unknown"
    source_coverage: SourceCoverage = Field(default_factory=SourceCoverage)
    price: Optional[float] = None
    dividend_yield: Optional[float] = None
    days_to_earnings: Optional[int] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    currency: str = "SEK"

    @property
    def symbol(self) -> str:
        return f"{self.ticker}.{self.exchange}"

    @property
    def display_name(self) -> str:
        return self.name or self.ticker.upper()

    @property
    def model_target(self) -> Optional[float]:
        return self.risk_reward.take_profit if self.risk_reward else None

    @property
    def model_upside(self) -> Optional[float]:
        return self.risk_reward.upside_pct if self.risk_reward else None

    @property
    def analyst_target(self) -> Optional[float]:
        return self.analyst.target_mean if self.analyst else None

    @property
    def analyst_upside(self) -> Optional[float]:
        if self.analyst and self.price:
            return self.analyst.upside(self.price)
        return None


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #
class Holding(BaseModel):
    ticker: str
    exchange: str
    shares: float
    average_cost: float
    currency: str = "SEK"
    current_price: Optional[float] = None
    sector: Optional[str] = None
    notes: Optional[str] = None
    # asset class: stock / etf / fund / cert / crypto. Drives scoring path
    # (stocks get the full fundamental thesis; others get technical-only signals)
    # and trade units (stocks/etf/cert priced in whole shares; funds in SEK).
    kind: str = "stock"
    # for instruments not priceable from free data (Swedish funds, SEK certs):
    # their current value in SEK (signals come from a tracked/proxy ticker).
    fixed_value_sek: Optional[float] = None
    # which account/broker the position lives in (e.g. "Avanza", "Coinbase").
    # Equity flows analyse the Avanza book; crypto coins are a separate sleeve.
    account: str = "Avanza"
    # for crypto: % of the position that is staked (has an unstaking cooldown
    # before it can be sold). Informational — surfaced as an execution caveat.
    staked_pct: Optional[float] = None

    @property
    def symbol(self) -> str:
        return f"{self.ticker}.{self.exchange}"

    @property
    def whole_share_instrument(self) -> bool:
        # priced in their own whole units on Yahoo; crypto/certs/funds we track
        # via an underlying/proxy, so those trade in SEK amounts instead.
        return self.kind in ("stock", "etf")


class HoldingAnalysis(BaseModel):
    holding: Holding
    name: Optional[str] = None
    current_price: Optional[float] = None
    price_sek: Optional[float] = None
    value_sek: Optional[float] = None
    cost_sek: Optional[float] = None
    unrealized_pct: Optional[float] = None
    weight_pct: Optional[float] = None
    score: Optional[ScoreBreakdown] = None
    analyst_target: Optional[float] = None
    analyst_upside: Optional[float] = None
    model_upside: Optional[float] = None
    action: Action = Action.HOLD
    confidence: Confidence = Confidence.LOW
    rationale: str = ""
    # exact trade instruction
    trade_shares: int = 0       # signed whole shares (+buy / -sell-trim); 0 for funds
    trade_sek: float = 0.0      # signed SEK amount of the suggested trade
    trade_note: str = ""        # e.g. "Trim 2 sh (~7,800 SEK) → 9%"


# --------------------------------------------------------------------------- #
# Crypto (separate sleeve — NO equity fundamentals exist for coins, so this
# uses a dedicated trend/momentum/quality-tier model, not the stock composite)
# --------------------------------------------------------------------------- #
class CryptoSignal(BaseModel):
    symbol: str                              # e.g. "BTC"
    name: str = ""                           # "Bitcoin"
    tier: int = 3                            # 1=BTC/ETH · 2=major L1 · 3=speculative alt
    price: Optional[float] = None            # USD
    action: Action = Action.HOLD            # nearest enum (drives colour/filtering)
    label: str = ""                          # precise verb: "ACCUMULATE" / "TRIM → BTC" / "IGNORE (dust)"
    headline: str = ""                       # one-line recommendation
    rationale: str = ""                      # the "why"
    biggest_risk: str = ""
    # score components (0–100, higher = better) + composite
    composite: float = 0.0
    trend: Optional[float] = None
    momentum: Optional[float] = None
    quality_tier: Optional[float] = None
    btc_relative: Optional[float] = None
    risk: Optional[float] = None
    is_mock: bool = False
    # raw technicals shown to the user (data, not opinion)
    ret_3m: Optional[float] = None
    ret_6m: Optional[float] = None
    ret_12m: Optional[float] = None
    drawdown_from_high: Optional[float] = None   # ≤0, distance below 1y high
    volatility: Optional[float] = None           # annualised
    rsi: Optional[float] = None
    above_ma50: Optional[bool] = None
    above_ma200: Optional[bool] = None
    # holdings-only fields (None for discovery rows)
    is_holding: bool = False
    qty: Optional[float] = None
    value_usd: Optional[float] = None
    value_sek: Optional[float] = None
    unrealized_pct: Optional[float] = None
    weight_pct: Optional[float] = None           # within the crypto sleeve
    staked_pct: Optional[float] = None
    trade_note: str = ""                         # "Sell ~75 SUI (~$54) → BTC"
    flags: list[str] = Field(default_factory=list)   # ["dust","staked","concentration","core"]

    @property
    def display_name(self) -> str:
        return self.name or self.symbol.upper()
