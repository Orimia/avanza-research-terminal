"""Keyless real-data provider via Yahoo Finance (yfinance).

The spec allows yfinance/Stooq as a *fallback* price source. Yahoo additionally
exposes reliable fundamentals via ``Ticker.info`` (margins/growth/ROE are already
fractions, matching the scoring engine), so this client provides real prices AND
real fundamentals with **no API key** — making "real data" the default when no
paid key is configured. It is still a fallback: when a keyed provider
(Börsdata/EODHD/Finnhub) is available it takes precedence.

Notes:
  * Yahoo's most recent daily bar is often NaN (incomplete); we ``dropna``.
  * Unknown/unsupported symbols return ``None`` -> router falls back to mock.
  * Every yfinance access is routed through the network audit log.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from src.config import get_config
from src.data.base import DataProvider
from src.models.schemas import (
    AnalystView,
    Catalysts,
    Fundamentals,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.currency import currency_for_exchange
from src.utils.logging import get_logger, log_network_call

log = get_logger("yahoo")

# EU universe ticker -> Yahoo symbol (per-venue suffixes).
_EU_YAHOO = {
    "ASML": "ASML.AS", "PRX": "PRX.AS", "AD": "AD.AS", "PHIA": "PHIA.AS",
    "INGA": "INGA.AS", "ASRNL": "ASRNL.AS",
    "SAP": "SAP.DE", "SIE": "SIE.DE", "ALV": "ALV.DE", "DTE": "DTE.DE",
    "BAS": "BAS.DE", "BAYN": "BAYN.DE", "IFX": "IFX.DE", "ADS": "ADS.DE",
    "MBG": "MBG.DE", "BMW": "BMW.DE", "VOW3": "VOW3.DE", "RHM": "RHM.DE",
    "MTX": "MTX.DE", "HEN3": "HEN3.DE", "MUV2": "MUV2.DE",
    "MC": "MC.PA", "OR": "OR.PA", "AIR": "AIR.PA", "SU": "SU.PA",
    "TTE": "TTE.PA", "RMS": "RMS.PA", "SAN": "SAN.PA", "BNP": "BNP.PA",
    "DG": "DG.PA", "EL": "EL.PA", "KER": "KER.PA", "CAP": "CAP.PA", "DSY": "DSY.PA",
    "STLAM": "STLAM.MI", "ENEL": "ENEL.MI", "ENI": "ENI.MI", "ISP": "ISP.MI",
    "UCG": "UCG.MI", "RACE": "RACE.MI",
    # additional EU names (held by users / extended coverage)
    "DBK": "DBK.DE", "STM": "STMPA.PA", "CBK": "CBK.DE", "P911": "P911.DE",
    "VNA": "VNA.DE", "NOVN": "NOVN.SW", "NESN": "NESN.SW", "ROG": "ROG.SW",
    # European UCITS ETFs (XETRA)
    "EXV3": "EXV3.DE", "XSX6": "XSX6.DE", "EXSA": "EXSA.DE", "EXV1": "EXV1.DE",
}

# Nordic exchange code -> Yahoo suffix (Copenhagen / Oslo / Helsinki)
_NORDIC_SUFFIX = {"ST": "ST", "STO": "ST", "OMX": "ST", "CO": "CO", "OL": "OL", "HE": "HE"}

# Crypto ticker -> Yahoo symbol overrides (most resolve as "<SYM>-USD", but a few
# collide with equities on Yahoo and need the numeric coin id).
_CRYPTO_YAHOO = {
    "SUI": "SUI20947-USD", "TON": "TON11419-USD", "SEI": "SEI-USD",
    "TIA": "TIA22861-USD", "RENDER": "RENDER-USD", "RNDR": "RENDER-USD",
}


def yahoo_symbol(ticker: str, exchange: str) -> Optional[str]:
    ex = (exchange or "").upper()
    if ex in {"US", "NYSE", "NASDAQ"}:
        return ticker
    if ex in {"CC", "CRYPTO"}:
        sym = (ticker or "").upper().replace("-USD", "")
        return _CRYPTO_YAHOO.get(sym, f"{sym}-USD")
    if ex in _NORDIC_SUFFIX:
        return f"{ticker}.{_NORDIC_SUFFIX[ex]}"
    if ex == "EU":
        return _EU_YAHOO.get(ticker)
    return None


def _num(info: dict, key: str) -> Optional[float]:
    v = info.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f else None  # drop NaN


def _bars_from_history(hist) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for idx, row in hist.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        try:
            bars.append(PriceBar(
                date=d, open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=float(row.get("Volume", 0) or 0),
            ))
        except (TypeError, ValueError):
            continue
    return bars


class YahooClient(DataProvider):
    name = "yahoo"

    def __init__(self) -> None:
        self.cfg = get_config()

    def available(self) -> bool:
        if not self.cfg.allow_network:
            return False
        try:
            import yfinance  # noqa: F401
        except Exception:
            return False
        return True

    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        if not self.available():
            return None
        sym = yahoo_symbol(ticker, exchange)
        if not sym:
            return None
        import yfinance as yf

        tk = yf.Ticker(sym)
        try:
            log_network_call(self.name, f"yfinance://{sym}/history", note="history 2y")
            hist = tk.history(period="2y", auto_adjust=True)
        except Exception as exc:  # pragma: no cover - network
            log.warning("Yahoo history failed for %s: %s", sym, exc)
            return None
        hist = hist.dropna(subset=["Close"])
        bars = _bars_from_history(hist)
        if not bars:
            return None

        info: dict = {}
        try:
            log_network_call(self.name, f"yfinance://{sym}/info", note="info")
            info = tk.info or {}
        except Exception as exc:  # pragma: no cover - network
            log.info("Yahoo info unavailable for %s: %s", sym, exc)

        ccy = currency_for_exchange(exchange) or info.get("currency") or "USD"
        fundamentals = self._fundamentals(info)
        quote = self._quote(bars, info, ccy)
        catalysts = self._catalysts(info)
        analyst = self._analyst(info)

        return StockData(
            ticker=ticker, exchange=exchange,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector"), country=info.get("country"),
            currency=ccy, quote=quote, fundamentals=fundamentals,
            price_history=bars, news=[], catalysts=catalysts, analyst=analyst,
            sources=["yahoo"],
            coverage=SourceCoverage(
                provider="yahoo", price=True,
                fundamentals=fundamentals is not None and fundamentals.available_fields() > 0,
                news=False, catalysts=catalysts is not None, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )

    def _quote(self, bars: list[PriceBar], info: dict, ccy: str) -> Quote:
        last = bars[-1]
        recent = bars[-20:]
        avg_vol = sum(b.volume for b in recent) / max(1, len(recent))
        return Quote(
            price=last.close, currency=ccy, market_cap=_num(info, "marketCap"),
            volume=last.volume, avg_volume=avg_vol, avg_turnover=avg_vol * last.close,
            as_of=datetime.now(timezone.utc),
        )

    def _fundamentals(self, info: dict) -> Optional[Fundamentals]:
        if not info:
            return None
        mcap = _num(info, "marketCap")
        fcf = _num(info, "freeCashflow")
        cash = _num(info, "totalCash")
        debt = _num(info, "totalDebt")
        ebitda = _num(info, "ebitda")
        ndte = ((debt - cash) / ebitda) if (debt is not None and cash is not None
                                            and ebitda not in (None, 0)) else None
        # dividend yield as a FRACTION. Prefer trailingAnnualDividendYield (always
        # a fraction); else Yahoo's dividendYield is a PERCENT (e.g. 3.95 = 3.95%,
        # 0.24 = 0.24%) so divide by 100.
        divy = _num(info, "trailingAnnualDividendYield")
        if divy is None:
            dpct = _num(info, "dividendYield")
            divy = dpct / 100.0 if dpct is not None else None
        f = Fundamentals(
            revenue_growth=_num(info, "revenueGrowth"),
            eps_growth=_num(info, "earningsGrowth"),
            gross_margin=_num(info, "grossMargins"),
            operating_margin=_num(info, "operatingMargins"),
            net_margin=_num(info, "profitMargins"),
            roe=_num(info, "returnOnEquity"),
            roic=None,  # Yahoo exposes ROA, not ROIC — don't mislabel
            fcf=fcf, cash=cash, debt=debt, net_debt_ebitda=ndte,
            pe=_num(info, "trailingPE"), forward_pe=_num(info, "forwardPE"),
            ev_ebitda=_num(info, "enterpriseToEbitda"),
            ev_sales=_num(info, "enterpriseToRevenue"),
            ps=_num(info, "priceToSalesTrailing12Months"),
            pb=_num(info, "priceToBook"),
            fcf_yield=(fcf / mcap) if (fcf is not None and mcap not in (None, 0)) else None,
            dividend_yield=divy, as_of=None,
        )
        return f

    def _catalysts(self, info: dict) -> Optional[Catalysts]:
        ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        if not isinstance(ts, (int, float)):
            return None
        try:
            nxt = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
        return Catalysts(next_earnings_date=nxt, days_to_earnings=(nxt - date.today()).days)

    def _analyst(self, info: dict) -> Optional[AnalystView]:
        target = _num(info, "targetMeanPrice")
        rec = info.get("recommendationKey")
        if target is None and rec is None:
            return None
        n = info.get("numberOfAnalystOpinions")
        return AnalystView(
            target_mean=target,
            target_high=_num(info, "targetHighPrice"),
            target_low=_num(info, "targetLowPrice"),
            n_analysts=int(n) if isinstance(n, (int, float)) else None,
            recommendation=rec if isinstance(rec, str) else None,
            recommendation_mean=_num(info, "recommendationMean"),
        )


def download_prices(entries: list[tuple[str, str]]) -> dict[str, StockData]:
    """Batch price-only fetch (one request) for screening/backtest — fast.

    Returns {symbol: StockData} with real prices, fundamentals omitted (missing).
    Not written to the persistent cache (callers cache as needed).
    """
    cfg = get_config()
    if not cfg.allow_network:
        return {}
    try:
        import yfinance as yf
    except Exception:
        return {}

    sym_map: dict[str, tuple[str, str]] = {}
    for ticker, exchange in entries:
        ys = yahoo_symbol(ticker, exchange)
        if ys:
            sym_map[ys] = (ticker, exchange)
    if not sym_map:
        return {}

    syms = list(sym_map)
    log_network_call("yahoo", f"yfinance://download/{len(syms)}", note="batch prices")
    try:
        bulk = yf.download(syms, period="2y", group_by="ticker",
                           progress=False, auto_adjust=True, threads=True)
    except Exception as exc:  # pragma: no cover - network
        log.warning("Yahoo batch download failed: %s", exc)
        return {}

    out: dict[str, StockData] = {}
    for ys, (ticker, exchange) in sym_map.items():
        try:
            sub = bulk[ys] if len(syms) > 1 else bulk
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            bars = _bars_from_history(sub)
            if not bars:
                continue
        except Exception:  # defensive on flaky/partial frames
            continue
        ccy = currency_for_exchange(exchange)
        last = bars[-1]
        recent = bars[-20:]
        avg_vol = sum(b.volume for b in recent) / max(1, len(recent))
        quote = Quote(price=last.close, currency=ccy, volume=last.volume,
                      avg_volume=avg_vol, avg_turnover=avg_vol * last.close,
                      as_of=datetime.now(timezone.utc))
        out[f"{ticker}.{exchange}"] = StockData(
            ticker=ticker, exchange=exchange, name=ticker, currency=ccy,
            quote=quote, fundamentals=None, price_history=bars, news=[],
            catalysts=None, sources=["yahoo"],
            coverage=SourceCoverage(provider="yahoo", price=True, fundamentals=False,
                                    news=False, catalysts=False, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )
    return out
