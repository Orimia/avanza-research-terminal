"""Crypto Screener & Signals page.

Two jobs the user asked for: (1) a DISCOVERY screen over a universe of coins, and
(2) thesis-aware SIGNALS on the tracked Coinbase holdings. Coins are scored on a
dedicated model (no equity fundamentals exist) and recommendations encode the
BTC-core / no-new-alts / don't-sell-at-the-lows thesis. Research only.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import get_config
from src.dashboard import ui
from src.models.schemas import Action, CryptoSignal, Holding
from src.storage.db import get_db
from src.universe.crypto import default_coinbase_holdings, name_of


def _usd(x: float | None) -> str:
    return "—" if x is None else (f"${x:,.2f}" if abs(x) < 100 else f"${x:,.0f}")


def page_crypto() -> None:
    cfg = get_config()
    st.header("Crypto")
    ui.disclaimer_banner()
    st.caption(
        "Coins have **no fundamentals** — scored on a separate **trend · momentum · "
        "quality-tier · BTC-relative · risk** model, never the stock thesis. "
        "**Thesis:** BTC is the only home for new money · keep the core (BTC/ETH/SOL) · "
        "consolidate the speculative tail into BTC · never panic-sell quality at the lows · "
        "ignore dust."
    )
    c1, c2 = st.columns([5, 1])
    if c2.button("Refresh", help="Pull fresh live coin prices & re-score"):
        ui.clear_crypto_cache()
        st.rerun()

    t_hold, t_disc, t_edit = st.tabs(["My holdings", "Discover", "Edit Coinbase book"])
    with t_hold:
        _holdings_view()
    with t_disc:
        _discovery_view(cfg)
    with t_edit:
        _editor_view()


# ------------------------------- holdings -------------------------------- #
def _holdings_view() -> None:
    data = ui.run_crypto_holdings()
    if data["n_holdings"] == 0:
        st.info("No coins tracked yet. Add your Coinbase book in the **Edit Coinbase book** tab.")
        return
    sigs = ui.unpack_crypto(data["signals"])
    if data["any_mock"]:
        st.warning("⚠️ Some coins are on MOCK data (offline / unavailable) — demo values only.")

    btc_w = next((s.weight_pct for s in sigs if s.symbol == "BTC"), 0) or 0
    core_w = sum(s.weight_pct or 0 for s in sigs if "core" in s.flags)
    actions = [s for s in sigs if s.label and not s.label.startswith(("HOLD", "IGNORE"))]
    ur = data["unrealized_pct"]

    m = st.columns(5)
    m[0].metric("Sleeve value", f"${data['value_usd']:,.0f}", help=f"≈ {data['value_sek']:,.0f} SEK")
    m[1].metric("Unrealized", f"{ur * 100:+.0f}%" if ur is not None else "—")
    m[2].metric("BTC weight", f"{btc_w:.0f}%")
    m[3].metric("Core (BTC/ETH/SOL)", f"{core_w:.0f}%")
    m[4].metric("To-do actions", len(actions))

    st.markdown("#### Do this")
    if not actions:
        st.success("Nothing to do — all core holds or immaterial dust. Stop tinkering; "
                   "this is a small, no-edge sleeve. Add nothing but BTC.")
    else:
        for s in actions:
            _holding_card(s, todo=True)

    with st.expander(f"All {len(sigs)} holdings — full detail", expanded=not actions):
        for s in sigs:
            _holding_card(s, todo=False)


def _holding_card(s: CryptoSignal, todo: bool) -> None:
    with st.container(border=True):
        top = st.columns([3, 1, 1])
        top[0].markdown(
            f"<span style='font-size:1.18rem;font-weight:800'>{s.symbol}</span> "
            f"<span style='color:#8b98a9'>· {s.display_name}</span> &nbsp; {ui.tier_chip(s.tier)}<br>"
            f"{ui.crypto_badge(s.action.value, s.label)} &nbsp; "
            f"{ui.crypto_flag_pills(s.flags, s.staked_pct)}",
            unsafe_allow_html=True)
        top[1].metric("Value", _usd(s.value_usd), help=f"{s.weight_pct:.0f}% of sleeve")
        top[2].metric("Unrealized", f"{s.unrealized_pct * 100:+.0f}%" if s.unrealized_pct is not None else "—")
        color = ui.ACTION_COLORS.get(s.action.value, "#6b7280")
        st.markdown(
            f"<div style='background:{color}14;border:0.5px solid {color}55;border-radius:12px;"
            f"padding:8px 13px;margin:4px 0'><b>{s.trade_note}</b></div>",
            unsafe_allow_html=True)
        st.markdown(f"<span style='color:#c4cdd9'>{s.headline}</span>", unsafe_allow_html=True)
        st.caption(s.rationale)
        st.caption(f"Risk · {s.biggest_risk}")


# ------------------------------ discovery -------------------------------- #
def _discovery_view(cfg) -> None:
    st.caption("Ranked by the crypto composite. **By design, only BTC (and ETH on a confirmed "
               "up-trend) can be a new-money BUY** — every alt is WATCH/AVOID no matter how it "
               "scores, because the thesis is you have no edge picking alts. The numbers are shown "
               "so you can see *why*, not so you'll act on them.")
    disc = ui.unpack_crypto(ui.run_crypto_discovery())
    if not disc:
        st.info("No market data available right now — hit Refresh, or check you're online.")
        return

    f1, f2 = st.columns([2, 3])
    tiers = f1.multiselect("Tiers", [1, 2, 3], default=[1, 2, 3],
                           format_func=lambda t: {1: "1 · blue-chip", 2: "2 · major L1",
                                                  3: "3 · speculative"}[t])
    only_buys = f2.toggle("Only show new-money candidates (ACCUMULATE)", value=False)
    rows = [s for s in disc if s.tier in tiers and (not only_buys or s.action == Action.BUY)]

    buys = [s for s in disc if s.action == Action.BUY]
    if buys:
        st.markdown("#### Sanctioned new-money buys")
        for s in buys:
            _disc_card(s)
    else:
        st.info("**No coin is a new-money buy right now** — neither BTC nor ETH is in a confirmed "
                "up-trend on current data. Under a BTC-only rule, that means: add nothing, wait.")

    st.markdown("#### Full market — score & data (informational)")
    held = {s.symbol for s in disc if s.is_holding}
    st.dataframe(pd.DataFrame([{
        "Coin": s.symbol + (" •" if s.symbol in held else ""), "Name": s.display_name,
        "Tier": s.tier, "Score": round(s.composite), "Verdict": s.label,
        "Trend": _n(s.trend), "Mom": _n(s.momentum), "BTC-rel": _n(s.btc_relative),
        "Risk": _n(s.risk), "3m %": _pct(s.ret_3m), "12m %": _pct(s.ret_12m),
        "From high": _pct(s.drawdown_from_high), "Vol %": _pct(s.volatility), "RSI": _n(s.rsi),
    } for s in rows]), width="stretch", hide_index=True)
    st.caption("• = you own it. Trend/Mom/BTC-rel/Risk are 0–100 sub-scores (higher = better). "
               "‘From high’ = distance below the 1-year high.")


def _disc_card(s: CryptoSignal) -> None:
    with st.container(border=True):
        c = st.columns([3, 1])
        own = " <span style='color:#4aa8ff;font-size:0.75rem'>· you own this</span>" if s.is_holding else ""
        c[0].markdown(
            f"<span style='font-size:1.15rem;font-weight:800'>{s.symbol}</span> "
            f"<span style='color:#8b98a9'>· {s.display_name}</span>{own} &nbsp; {ui.tier_chip(s.tier)}<br>"
            f"{ui.crypto_badge(s.action.value, s.label)}", unsafe_allow_html=True)
        c[1].metric("Score", f"{s.composite:.0f}")
        st.markdown(f"<span style='color:#c4cdd9'>{s.headline}</span>", unsafe_allow_html=True)
        st.caption(s.rationale)


def _n(x: float | None) -> float | None:
    return None if x is None else round(x)


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 1)


# ------------------------------- editor ---------------------------------- #
_EDIT_COLS = ["ticker", "shares", "average_cost", "staked_pct", "notes"]


def _editor_view() -> None:
    st.caption("Your Coinbase book — **manual updates only** (no broker login, no API). "
               "Edit balances/cost/staking after you trade, then Save. Coins are priced live "
               "via Yahoo `<SYM>-USD`; cost is USD per coin.")
    holdings = get_db().crypto_holdings_all()
    df = pd.DataFrame([{
        "ticker": h.ticker, "shares": h.shares, "average_cost": h.average_cost,
        "staked_pct": h.staked_pct, "notes": h.notes or name_of(h.ticker),
    } for h in holdings]) if holdings else pd.DataFrame(columns=_EDIT_COLS)

    edited = st.data_editor(df, num_rows="dynamic", width="stretch", key="crypto_editor",
                            column_config={
                                "ticker": st.column_config.TextColumn("Coin", help="e.g. BTC, ETH, SOL"),
                                "shares": st.column_config.NumberColumn("Units", format="%.8f"),
                                "average_cost": st.column_config.NumberColumn("Avg cost (USD)", format="%.4f"),
                                "staked_pct": st.column_config.NumberColumn("Staked %", min_value=0, max_value=100),
                            })
    c1, c2 = st.columns([1, 4])
    if c1.button("Save", type="primary"):
        get_db().crypto_holdings_replace(_df_to_crypto(edited))
        ui.clear_crypto_cache()
        st.success("Saved.")
        st.rerun()
    if c2.button("Reset to my Coinbase snapshot"):
        get_db().crypto_holdings_replace(default_coinbase_holdings())
        ui.clear_crypto_cache()
        st.rerun()


def _df_to_crypto(df: pd.DataFrame) -> list[Holding]:
    out = []
    for _, row in df.iterrows():
        tk = str(row.get("ticker", "") or "").strip().upper().replace("-USD", "")
        if not tk:
            continue
        try:
            staked = row.get("staked_pct")
            out.append(Holding(
                ticker=tk, exchange="CC", shares=float(row.get("shares") or 0),
                average_cost=float(row.get("average_cost") or 0), currency="USD",
                kind="crypto", account="Coinbase",
                staked_pct=float(staked) if staked not in (None, "") and pd.notna(staked) else None,
                notes=(str(row.get("notes", "") or "").strip() or name_of(tk)),
            ))
        except (ValueError, TypeError):
            continue
    return out
