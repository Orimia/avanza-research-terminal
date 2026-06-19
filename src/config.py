"""Configuration loader.

Loads ``config.yaml`` and environment variables (from ``.env`` if present).
A single cached :class:`Config` is the source of truth for tunables, API keys
and behaviour flags. No secret is ever written back to disk.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

try:  # optional, but recommended
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is in requirements
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Thin wrapper around the parsed YAML plus environment access."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # -- dotted lookups ----------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    # -- environment -------------------------------------------------------
    @staticmethod
    def env(name: str, default: str | None = None) -> str | None:
        val = os.getenv(name, default)
        if val is not None:
            val = val.strip()
        return val or default

    def has_key(self, name: str) -> bool:
        return bool(self.env(name))

    @property
    def allow_network(self) -> bool:
        # config.force_mock overrides everything towards mock
        if self.get("data.force_mock", False):
            return False
        return _to_bool(self.env("ALLOW_NETWORK"), default=True)

    @property
    def base_currency(self) -> str:
        return self.get("app.base_currency", "SEK")

    @property
    def disclaimer(self) -> str:
        return self.get("app.disclaimer", "This is not personal financial advice.")

    @property
    def portfolio_value_sek(self) -> float:
        return float(self.get("app.portfolio_value_sek", 250000))

    def scoring_weights(self) -> dict[str, float]:
        return dict(self.get("scoring.weights", {}))


def _default_config() -> dict[str, Any]:
    """Minimal safe defaults if config.yaml is missing (keeps app runnable)."""
    return {
        "app": {"base_currency": "SEK", "portfolio_value_sek": 250000,
                "disclaimer": "This is not personal financial advice."},
        "data": {"force_mock": False, "price_history_days": 400,
                 "fx": {"static": {"USDSEK": 10.55, "EURSEK": 11.30, "SEKSEK": 1.0}}},
        "scoring": {"weights": {"quality": 0.2, "growth": 0.2, "momentum": 0.2,
                                 "valuation": 0.15, "catalyst": 0.15, "risk": 0.1}},
        "decisions": {"buy_min_composite": 68, "watch_min_composite": 56,
                       "avoid_max_composite": 42, "min_risk_reward": 1.5,
                       "hold_floor_composite": 50, "sell_floor_composite": 40},
        "risk": {"max_new_position_pct": 0.05, "max_high_risk_position_pct": 0.02,
                  "max_speculative_exposure_pct": 0.15, "max_daily_new_buying_pct": 0.10,
                  "default_stop_pct": 0.12, "default_take_profit_pct": 0.25,
                  "position_vs_adv_warn": 0.10, "high_volatility_annual": 0.45},
        "filters": {"min_avg_turnover_sek": 5_000_000, "min_market_cap_sek": 1_000_000_000,
                     "exclude_penny_below_local": 5.0, "allow_small_cap": False},
        "universe": {"watchlist": [], "limits": {"nordic": 60, "eu": 40, "us": 60}},
        "reports": {"use_llm": False, "show_institutional_lenses": True},
        "logging": {"level": "INFO", "log_network_calls": True},
    }


@lru_cache(maxsize=1)
def get_config() -> Config:
    if load_dotenv is not None:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    else:
        data = _default_config()
    return Config(data)


def reload_config() -> Config:
    """Clear the cache and re-read config.yaml (used by the Settings page)."""
    get_config.cache_clear()
    return get_config()
