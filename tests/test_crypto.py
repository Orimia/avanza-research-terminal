"""Tests for the crypto sleeve: symbol routing, scoring, thesis-aware decisions,
and account isolation. All offline (synthetic StockData / direct signals)."""
from datetime import date, datetime, timedelta, timezone

from src.data.base import region_for_exchange
from src.models.schemas import (
    Action,
    CryptoSignal,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.scoring.crypto import build_crypto_signal, decide_crypto_holding, decide_crypto_new
from src.universe.crypto import crypto_screen_entries, default_coinbase_holdings, tier_of
from src.utils.currency import currency_for_exchange


# --- helpers -------------------------------------------------------------- #
def _mk(closes: list[float], ticker: str = "X", mock: bool = False) -> StockData:
    bars = [PriceBar(date=date(2024, 1, 1) + timedelta(days=i), open=c, high=c, low=c, close=c)
            for i, c in enumerate(closes)]
    return StockData(ticker=ticker, exchange="CC", currency="USD", price_history=bars,
                     quote=Quote(price=closes[-1], currency="USD"),
                     coverage=SourceCoverage(is_mock=mock), is_mock=mock,
                     fetched_at=datetime.now(timezone.utc))


_UP = [100 * (1.004 ** i) for i in range(300)]      # strong, steady up-trend
_DOWN = [320 * (0.992 ** i) for i in range(300)]     # steady down-trend


# --- symbol / region / currency routing ----------------------------------- #
def test_crypto_symbol_routing():
    from src.data.yahoo_client import yahoo_symbol
    assert yahoo_symbol("BTC", "CC") == "BTC-USD"
    assert yahoo_symbol("eth", "CC") == "ETH-USD"
    assert yahoo_symbol("SUI", "CC") == "SUI20947-USD"      # special-cased id
    assert yahoo_symbol("ETH-USD", "CC") == "ETH-USD"       # idempotent on -USD
    assert region_for_exchange("CC") == "crypto"
    assert currency_for_exchange("CC") == "USD"


# --- scoring: tier + trend ------------------------------------------------ #
def test_tier_quality_and_trend_direction():
    up = build_crypto_signal(_mk(_UP), tier=2, name="Up", btc_ret_3m=0.0)
    down = build_crypto_signal(_mk(_DOWN), tier=2, name="Down", btc_ret_3m=0.0)
    assert up.composite > down.composite                    # up-trend scores higher
    assert up.above_ma200 is True and down.above_ma200 is False
    # tier raises the quality component (BTC/ETH durability proxy)
    t1 = build_crypto_signal(_mk(_UP), tier=1, name="T1", btc_ret_3m=0.0)
    t3 = build_crypto_signal(_mk(_UP), tier=3, name="T3", btc_ret_3m=0.0)
    assert t1.quality_tier > t3.quality_tier and t1.composite > t3.composite


def test_btc_relative_outperformance():
    # same price path, but compared against a BTC that fell 30% -> outperforming
    s = build_crypto_signal(_mk(_UP), tier=2, name="X", btc_ret_3m=-0.30)
    assert s.btc_relative is not None and s.btc_relative > 70


# --- discovery decisions (thesis: BTC-only new money) --------------------- #
def test_discovery_btc_accumulate_on_uptrend():
    sig = build_crypto_signal(_mk(_UP, ticker="BTC"), tier=1, name="Bitcoin", btc_ret_3m=0.0)
    decide_crypto_new(sig)
    assert sig.action == Action.BUY and "ACCUMULATE" in sig.label


def test_discovery_strong_alt_is_watch_not_buy():
    sig = build_crypto_signal(_mk(_UP, ticker="NEAR"), tier=2, name="NEAR", btc_ret_3m=-0.2)
    decide_crypto_new(sig)
    assert sig.action == Action.WATCH               # never BUY an alt, however it screens
    assert "no new alt" in sig.label.lower() or "watch" in sig.label.lower()


def test_discovery_weak_alt_avoided():
    sig = build_crypto_signal(_mk(_DOWN, ticker="DOGE"), tier=3, name="Dogecoin", btc_ret_3m=0.0)
    decide_crypto_new(sig)
    assert sig.action == Action.AVOID


# --- holding decisions (keep core · consolidate tail · ignore dust) ------- #
def _holding(symbol, tier, value_usd, weight, qty=1.0, staked=None, composite=50):
    return CryptoSignal(symbol=symbol, tier=tier, value_usd=value_usd, weight_pct=weight,
                        qty=qty, staked_pct=staked, composite=composite, is_holding=True)


def test_holding_core_holds():
    for sym in ("BTC", "ETH", "SOL"):
        s = _holding(sym, 1 if sym in ("BTC", "ETH") else 2, 200, 30)
        decide_crypto_holding(s)
        assert s.action == Action.HOLD and s.label.startswith("HOLD")
        assert "core" in s.flags


def test_holding_tail_consolidates_to_btc():
    s = _holding("XRP", 2, 50, 10, qty=42.0, composite=48)
    decide_crypto_holding(s)
    assert s.action in (Action.SELL, Action.TRIM)
    assert "→ BTC" in s.trade_note and "XRP" in s.trade_note


def test_holding_dust_ignored():
    s = _holding("VET", 3, 1.9, 0.3, qty=397.0)
    decide_crypto_holding(s)
    assert s.label.startswith("IGNORE") and "dust" in s.flags


def test_holding_concentration_flag():
    s = _holding("ETH", 1, 400, 60)          # 60% > 55% cap
    decide_crypto_holding(s)
    assert "concentration" in s.flags and "don't add" in s.headline.lower()


def test_holding_staked_sell_needs_unstake():
    s = _holding("ADA", 3, 50, 8, qty=24.0, staked=87.0, composite=40)
    decide_crypto_holding(s)
    assert s.action in (Action.SELL, Action.TRIM) and "unstake" in s.trade_note.lower()


# --- account isolation + seed --------------------------------------------- #
def test_coinbase_seed_and_isolation():
    from src.storage.db import get_db
    db = get_db()
    seed = default_coinbase_holdings()
    assert len(seed) >= 1 and any(h.ticker == "BTC" for h in seed)
    db.crypto_holdings_replace(seed)
    got = {h.ticker: h for h in db.crypto_holdings_all()}
    assert set(got) == {h.ticker for h in seed}
    assert got["BTC"].account == "Coinbase"
    # the crypto sleeve must NOT leak into the equity portfolio table
    assert all(h.exchange != "CC" for h in db.portfolio_all())


def test_universe_entries_use_cc_exchange():
    entries = crypto_screen_entries(limit=5)
    assert all(ex == "CC" for _, ex in entries)
    assert tier_of("BTC") == 1 and tier_of("VET") == 3


# --- mock handling: discovery skips synthetic, holdings show flagged --------- #
def test_discovery_skips_mock_data():
    # tests run offline (ALLOW_NETWORK=false) → every coin resolves to mock, so
    # the discovery screen must be EMPTY rather than ranking synthetic prices.
    from src.portfolio.crypto_account import run_crypto_discovery
    assert run_crypto_discovery(limit=6) == []


def test_holdings_still_shown_when_mock():
    # holdings, unlike discovery, must still appear offline — flagged as mock.
    from src.portfolio.crypto_account import analyze_crypto_holdings
    from src.storage.db import get_db
    get_db().crypto_holdings_replace(default_coinbase_holdings())
    rv = analyze_crypto_holdings()
    n = len(default_coinbase_holdings())
    assert rv.n_holdings == n and len(rv.signals) == n and rv.any_mock is True


# --- automatic rotating backups ------------------------------------------- #
def test_db_backup_creates_and_rotates(tmp_path):
    import sqlite3

    from src.storage.db import Database
    db = Database(tmp_path / "t.db")
    for i in range(3):
        db.backup(keep=2, reason=f"r{i}")
    backups = sorted((tmp_path / "backups").glob("t-*.db"))
    assert len(backups) == 2                          # rotated to the newest 2
    c = sqlite3.connect(str(backups[-1]))
    tbls = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    assert {"portfolio", "crypto_holdings"} <= tbls   # a real, schema-complete copy
