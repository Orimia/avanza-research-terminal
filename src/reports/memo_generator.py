"""Assemble the full decision memo.

The deterministic engine produces the complete memo with **no** LLM. If
``reports.use_llm`` is enabled AND ``ANTHROPIC_API_KEY`` is set, an optional,
fully-isolated narrative synthesis is prepended. The LLM is instructed to use
ONLY the memo it is given and never to invent data; any failure silently falls
back to the deterministic memo.
"""
from __future__ import annotations

from src.config import Config, get_config
from src.models.schemas import Recommendation, StockData
from src.reports import templates as T
from src.reports.citation_manager import CitationManager
from src.utils.logging import get_logger

log = get_logger("memo")


def _header(data: StockData, rec: Recommendation, cfg: Config) -> str:
    lines = [f"# {rec.action.value} — {rec.name or rec.ticker} ({rec.symbol})", ""]
    if data.is_mock:
        lines.append("> ⚠️ **MOCK DATA** — no API key/network for this name. "
                     "Numbers are synthetic and for UI/demo only; not investable signal.")
        lines.append("")
    lines.append(f"> _{cfg.disclaimer}_  ·  Research only — no broker login, no orders, "
                 "no certificates, whole shares only.")
    lines.append("")
    lines.append(f"`freshness: {rec.data_freshness}` · "
                 f"`coverage: {rec.source_coverage.quality}` · "
                 f"`sources: {', '.join(data.sources) or 'none'}`")
    return "\n".join(lines)


def generate_memo(data: StockData, rec: Recommendation,
                  opp_cost: dict[str, str] | None = None,
                  cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    opp_cost = opp_cost or {}

    cites = CitationManager()
    cites.add(data.news)

    parts = [
        _header(data, rec, cfg),
        T.exec_summary(rec),
        T.fundamentals_section(data),
        T.technicals_section(rec.technicals, data) if rec.technicals else "## C. Technical & sentiment\n- _No price history._",
        T.bull_case(rec),
        T.bear_case(data, rec),
        T.opportunity_cost_section(opp_cost),
        T.portfolio_fit_section(rec),
        T.final_decision_section(rec),
        T.self_attack_section(data, rec),
    ]
    if cfg.get("reports.show_institutional_lenses", True):
        parts.append(T.lenses_section(data, rec))
    parts.append(cites.render())
    parts.append(f"\n---\n_{cfg.disclaimer}_")

    deterministic = "\n\n".join(parts)

    if cfg.get("reports.use_llm", False) and cfg.has_key("ANTHROPIC_API_KEY"):
        narrative = _maybe_llm_narrative(deterministic, rec, cfg)
        if narrative:
            # insert the synthesis right after the header (parts[0]); no dup header
            return "\n\n".join([parts[0], f"## Synthesis (LLM)\n{narrative}", *parts[1:]])
    return deterministic


def _maybe_llm_narrative(memo: str, rec: Recommendation, cfg: Config) -> str | None:
    """Optional LLM synthesis. Isolated; returns None on any problem."""
    try:
        import anthropic  # noqa: F401
    except Exception:
        log.info("anthropic SDK not installed; skipping LLM narrative.")
        return None
    try:
        client = anthropic.Anthropic(api_key=cfg.env("ANTHROPIC_API_KEY"))
        model = cfg.env("ANTHROPIC_MODEL", "claude-opus-4-8")
        prompt = (
            "You are an institutional analyst. Using ONLY the deterministic memo below, "
            "write a 4-6 sentence synthesis. Do NOT invent any number or fact not present. "
            "If something is marked '—missing—', say it is missing. Keep it concise and "
            "non-theatrical. End by restating the action and confidence.\n\n"
            f"ACTION={rec.action.value} CONFIDENCE={rec.confidence.value}\n\n"
            f"MEMO:\n{memo}"
        )
        log.info("Calling Anthropic for memo narrative (model=%s)", model)
        resp = client.messages.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    except Exception as exc:  # pragma: no cover - network/optional
        log.warning("LLM narrative failed, using deterministic memo: %s", exc)
        return None
