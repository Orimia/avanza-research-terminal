# Changelog

All notable changes to this project are documented here. This is a research
tool — not financial advice.

## 0.1.0

Initial public release.

### Added
- **Screening & scoring** — Sweden / EU / US equity universes filtered by
  liquidity, market cap and penny rules, then scored on Quality, Growth,
  Momentum, Valuation, Catalyst and Risk into a weighted composite, with
  whole-share SEK position sizing.
- **Decision memos** — deterministic (no LLM required) BUY / HOLD / TRIM /
  SELL / AVOID memos with institutional lenses, bull/bear cases, opportunity
  cost and a self-attack pre-mortem.
- **Always-on engine** — market-hours-gated scanner, state-based signal
  de-duplication, Telegram/email alerts, morning/close digests, portfolio
  pulse, and Docker/Fly deploy.
- **Crypto sleeve** — a separate trend / momentum / quality-tier / BTC-relative
  model (coins have no fundamentals), a discovery screener, and thesis-aware
  holding signals, kept isolated from equity weights.
- **Apple-inspired dashboard** — real-button navigation, SF Pro typography.
- **Reliability** — automatic rotating SQLite backups on every save.
- **Safety** — keyless real data via Yahoo with deterministic mock fallback;
  missing data is never invented; guardrail tests fail the build on any
  broker-automation identifier.
