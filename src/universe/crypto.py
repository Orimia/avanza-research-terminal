"""Crypto universe + metadata for the screener and holdings monitor.

Coins have **no fundamentals** (no margins, P/E, ROE, analyst targets), so they
are NOT scored on the equity composite. This module just supplies the screenable
universe and a quality *tier* (a crude, honest stand-in for "durability"):

    tier 1  →  BTC, ETH            (largest, ETF/institutional, lead recoveries)
    tier 2  →  major L1/L0 alts    (real ecosystems, but higher beta)
    tier 3  →  speculative alts     (narrative-driven; most never reclaim highs)

Yahoo serves all of these keyless as ``<SYM>-USD`` (a few overrides live in
``yahoo_client._CRYPTO_YAHOO``). Exchange code ``CC`` routes here.
"""
from __future__ import annotations

from src.models.schemas import Holding

# (symbol, display name, tier). Ordered roughly by market cap within tier.
CRYPTO_UNIVERSE: list[tuple[str, str, int]] = [
    ("BTC", "Bitcoin", 1), ("ETH", "Ethereum", 1),
    ("SOL", "Solana", 2), ("BNB", "BNB", 2), ("XRP", "XRP", 2),
    ("ADA", "Cardano", 2), ("AVAX", "Avalanche", 2), ("DOT", "Polkadot", 2),
    ("LINK", "Chainlink", 2), ("LTC", "Litecoin", 2), ("BCH", "Bitcoin Cash", 2),
    ("TRX", "TRON", 2), ("ATOM", "Cosmos", 2), ("NEAR", "NEAR Protocol", 2),
    ("UNI", "Uniswap", 2), ("XLM", "Stellar", 2),
    ("APT", "Aptos", 3), ("ARB", "Arbitrum", 3), ("OP", "Optimism", 3),
    ("SUI", "Sui", 3), ("INJ", "Injective", 3), ("ICP", "Internet Computer", 3),
    ("SEI", "Sei", 3), ("TIA", "Celestia", 3), ("DOGE", "Dogecoin", 3),
    ("VET", "VeChain", 3), ("ALCX", "Alchemix", 3),
]

_META: dict[str, tuple[str, int]] = {s: (n, t) for s, n, t in CRYPTO_UNIVERSE}


def name_of(symbol: str) -> str:
    sym = (symbol or "").upper().replace("-USD", "")
    return _META.get(sym, (sym, 3))[0]


def tier_of(symbol: str) -> int:
    sym = (symbol or "").upper().replace("-USD", "")
    return _META.get(sym, (sym, 3))[1]


def crypto_screen_entries(limit: int | None = None) -> list[tuple[str, str]]:
    """(ticker, exchange) pairs for the discovery screen — all routed via 'CC'."""
    syms = CRYPTO_UNIVERSE if limit is None else CRYPTO_UNIVERSE[:limit]
    return [(s, "CC") for s, _, _ in syms]


# --------------------------------------------------------------------------- #
# Example Coinbase seed so the crypto sleeve renders out of the box. These are
# ILLUSTRATIVE figures only — not real holdings, not advice. Replace them with
# your own positions in the dashboard (Crypto -> Edit), which persists to the
# local, git-ignored database.
# --------------------------------------------------------------------------- #
def default_coinbase_holdings() -> list[Holding]:
    # (symbol, qty, average_cost_usd, staked_pct) — example data, edit in-app
    seed = [
        ("BTC", 0.01, 60000.0, None),
        ("ETH", 0.5, 2500.0, 25.0),
        ("SOL", 5.0, 150.0, 50.0),
        ("ADA", 100.0, 0.60, 80.0),
    ]
    return [
        Holding(ticker=sym, exchange="CC", shares=qty, average_cost=cost,
                currency="USD", kind="crypto", account="Coinbase",
                staked_pct=staked, notes=name_of(sym))
        for sym, qty, cost, staked in seed
    ]
