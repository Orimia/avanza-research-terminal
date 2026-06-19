# 📈 avanza-research-terminal

[![CI](https://github.com/Orimia/avanza-research-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Orimia/avanza-research-terminal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Tests](https://img.shields.io/badge/tests-80%20passing-brightgreen)

A **local stock research terminal** that screens Swedish, EU and US equities, ranks
opportunities, analyzes your existing holdings, and produces concise institutional-style
**BUY / HOLD / TRIM / SELL / AVOID** decision memos — so you can place **whole-share orders
manually in Avanza yourself**.

> ## 🔒 This is a research tool, not a trading bot
> It **never** logs into Avanza, **never** places orders, **never** stores broker
> credentials, and **never** uses unofficial Avanza APIs or scrapes Avanza pages.
> It produces a dashboard and a daily decision memo. **You** place every order manually.
> Whole shares only · no options · certificates disabled by default · base currency **SEK**.
>
> **This is not personal financial advice.**

It runs **fully on deterministic mock data with zero API keys** so you can explore the whole
UI immediately. Real data providers activate automatically when you add keys to `.env`.

---

## Engineering highlights

- **Deterministic, testable core** — scoring, sizing and decisions are pure functions with
  **80 offline tests**; no LLM in the critical path. Missing data stays `None`, never invented.
- **Clean provider abstraction** — keyed sources, keyless Yahoo, and a deterministic mock all
  sit behind one interface; a real symbol's missing field is never back-filled with a mock number.
- **Always-on engine** with **state-based de-duplication** — you get *new* signals, not spam.
- **Two asset classes, two models** — equities use a fundamentals composite; crypto uses a
  separate trend / momentum / quality-tier model, **isolated so it can't distort equity math**.
- **Hard safety guardrails** — a test fails the build if any source file contains
  order-execution or credential-capture identifiers. Research-only, by construction.

---

## What it does

- **Screens** Sweden / EU / US universes with liquidity, market-cap and penny filters.
- **Scores** every name on Quality, Growth, Momentum, Valuation, Catalyst, Risk and
  Liquidity, then combines them into a weighted **composite score** (weights editable in
  `config.yaml`).
- **Sizes** positions in **SEK with whole-share counts**, enforcing your risk limits
  (max position %, high-risk cap, daily buy budget) and flagging liquidity/FX risk.
- **Reviews your portfolio**: per-holding BUY/HOLD/TRIM/SELL, weakest holding, best
  replacement, sector/country/currency exposure, concentration, stress tests.
- **Writes decision memos** (deterministic — no LLM required) using ten institutional
  lenses (Goldman, Morgan Stanley, McKinsey, BlackRock, Berkshire, Blackstone,
  Citadel/Point72, Bridgewater, activist short-seller, CIO) plus bull/bear cases, an
  opportunity-cost comparison and a **self-attack pre-mortem**.
- **Cites sources**: every news item carries source name, timestamp and URL. Missing data
  is shown as `—missing—`, never invented.
- **Backtests** the momentum signal with walk-forward validation (with explicit
  survivorship-bias warnings).
- **Crypto sleeve** (kept entirely separate from equities — coins have no fundamentals):
  a dedicated **trend / momentum / quality-tier / BTC-relative / risk** model, a discovery
  screener, and thesis-aware signals on a tracked crypto account (keep the core, consolidate
  the speculative tail into BTC, ignore dust) — isolated so it never distorts equity weights.

---

## Quickstart (works with no API keys)

```bash
# 1. Clone / open the project
cd avanza-research-terminal

# 2. Create a virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (optional) create your .env — you can skip this and run on mock data
cp .env.example .env

# 5. Launch the dashboard
streamlit run src/dashboard/app.py
```

The dashboard opens at <http://localhost:8501>. The sidebar shows **🟡 MOCK** (no keys) or
**🟢 LIVE** (keys present). On the **Portfolio Review** page click **Load sample portfolio**
to see the full flow with the bundled `examples/sample_portfolio.csv`.

---

## 🟢 Always-on engine (live alerts) — the main event

The dashboard is the read UI. The **engine** is the always-on part: a scheduled
scanner that refreshes SE/EU/US data, detects *actionable transitions*, de-duplicates
them against stored state (so you only get **new** signals, never spam), and **pushes
Telegram + email alerts** plus a morning and post-close digest.

**Signal types** → `NEW_BUY`, holding `TRIM`/`SELL` action changes, trailing **stop-loss**
& cost-based **take-profit** hits, **big moves**, **breakouts** (new highs), **RSI** extremes,
and **imminent earnings**. Each carries an action (BUY/TRIM/SELL/WATCH/REVIEW) and severity.

**Schedule** (config in `config.yaml → engine`): intraday scan every ~20 min *during
Stockholm/EU/US market hours*, a morning digest (08:15), and a post-close digest (22:15),
all in `Europe/Stockholm`.

### Run it

```bash
python -m src.engine.scheduler            # run forever (daemon)
python -m src.engine.scheduler once       # one full scan + send (cron-style)
python -m src.engine.scheduler intraday   # one intraday scan + send
python -m src.engine.scheduler dry-run    # full scan, PRINT the message, send nothing
```

`dry-run` is the best first check — it prints exactly what would be sent.

### Wire up notifications (you do this once)

**Telegram (recommended):** message **@BotFather** → `/newbot` → copy the token into
`TELEGRAM_BOT_TOKEN` in `.env`. DM your new bot once, then find your chat id the easy way:

```bash
python -m src.alerts.telegram          # prints chats that messaged your bot
python -m src.engine.scheduler test-alert   # send a test alert to verify
```

Put the id in `TELEGRAM_CHAT_ID`. (Or use the **Settings → Notifications** page: *Find my
chat id* + *Send test alert* buttons.)

**Email:** set `ALERT_EMAIL_SMTP_HOST/PORT/USERNAME/PASSWORD/ALERT_EMAIL_TO` in `.env`
(for Gmail use an App Password). No broker credentials are ever requested or used.

Choose channels in `config.yaml → engine.alerts.channels: [telegram, email]`.

### Deploy 24/7 (so it runs when your Mac is off)

**Docker Compose (local box / any VPS)** — runs the engine *and* dashboard, sharing one DB:

```bash
cp .env.example .env            # fill in Telegram/email keys
docker compose up -d --build    # engine pushes alerts; dashboard at :8501
```

**Fly.io (managed, always-on worker)** — see `fly.toml`:

```bash
fly launch --no-deploy
fly volumes create art_data --size 1 --region arn
fly secrets set TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
fly deploy
```

The **Alerts & Engine** dashboard page shows the live signal feed, engine health
(last scan, status), and a **Run a scan now** button with a message preview.

---

## Enabling live data (optional)

Copy `.env.example` to `.env` and fill in whichever keys you have. **All are optional.**

| Variable | Purpose | Region |
|---|---|---|
| `BORSDATA_API_KEY` | Primary Nordic fundamentals, reports, prices | Sweden / Nordic |
| `EODHD_API_KEY` | Global fundamentals, EOD prices, news | US / EU |
| `FINNHUB_API_KEY` | Global quotes, metrics, news, earnings dates | US / EU |
| `FX_API_KEY` | (optional) live USD/SEK, EUR/SEK — static fallback built in | FX |
| `ANTHROPIC_API_KEY` | (optional) LLM memo narrative — deterministic memo works without it | — |
| `TELEGRAM_*`, `ALERT_EMAIL_*` | (optional) alerts | — |
| `ALLOW_NETWORK` | set `false` to force offline/mock even with keys | — |

- With a key present, the relevant **real client activates behind a clean interface**. If a
  call fails or a field is unavailable, that field stays **missing** (it is never back-filled
  with mock numbers for a real symbol).
- **Every outbound network call is logged** to `logs/network.jsonl` and shown on the
  **Settings → Data freshness** panel. There are no hidden network calls.
- **There is no Avanza key, and there never will be.** Do not put broker credentials in `.env`.

---

## Portfolio CSV format

Create/maintain this file yourself (export your holdings from Avanza manually, then format
as CSV — the app does **not** connect to Avanza):

```csv
ticker,exchange,shares,average_cost,currency,current_price_optional,sector,notes
VOLV-B,ST,40,245.0,SEK,,Industrials,Core Nordic industrial
NVDA,US,8,95.0,USD,,Technology,AI infrastructure
```

`current_price_optional` may be blank — prices are then fetched from the data layer.
Exchanges: `ST` (Stockholm), `US`, `EU`.

---

## Dashboard pages

**Apple-inspired dark theme** with real-button navigation and SF Pro typography. Pages:

1. **Overview / Today** — glanceable home: market-open chips (SE/EU/US), engine status,
   today's "what to do" (BUY/TRIM/SELL signals), latest-signal feed, holdings snapshot,
   **live auto-refresh**.
2. **Alerts & Engine** — live signal feed (filter by severity/type/symbol), engine health,
   **run-a-scan-now** with message preview.
3. **Daily Opportunities** — ranked BUY / WATCH / AVOID, filters, daily buy-budget tracker.
4. **Crypto Signals** — a discovery screener plus thesis-aware signals on a tracked crypto
   account: BTC-only-new-money rule, core vs. speculative-tail handling, concentration and
   staking flags, dust suppression — all on a model separate from the equity thesis.
5. **Portfolio Review** — per-holding decision, weakest holding, replacements, opportunity cost.
6. **Stock Deep Dive** — full memo for any ticker (dark candlestick, score bars, clickable
   news, add-to-watchlist, save memo).
7. **Risk Dashboard** — country/currency/sector exposure, concentration (HHI), vol & drawdown
   proxies, portfolio-weighted stress test.
8. **Backtest** — momentum backtest + walk-forward, with survivorship-bias warnings.
9. **Settings** — API status, **Notifications setup** (test-alert + chat-id finder), network
   audit log, scoring weights, risk limits, watchlist editor.

---

## Scoring & decisions (deterministic)

Composite = weighted average of sub-scores (all 0–100, higher = better), renormalised over
whatever data is available. Default weights (`config.yaml`):

```
Quality 20% · Growth 20% · Momentum 20% · Valuation 15% · Catalyst 15% · Risk 10%
```
Liquidity is scored separately and used as a gate/penalty.

- **BUY** — composite ≥ threshold, acceptable R/R, momentum & valuation OK, liquid.
- **WATCH** — good idea but entry/uncertainty not yet attractive.
- **HOLD / TRIM / SELL** — for existing holdings (thesis intact / oversized or mediocre / broken).
- **AVOID** — detached valuation, weak catalyst, poor liquidity, debt/dilution risk, or hype.
- **Confidence** (High/Medium/Low) reflects data coverage, signal agreement, liquidity and R/R.
  **Mock data never yields High confidence.**

All thresholds and risk limits live in `config.yaml` and reload from **Settings**.

---

## Optional: LLM memo narrative

The deterministic engine produces the **complete** memo with no LLM. If you set
`reports.use_llm: true` in `config.yaml` **and** provide `ANTHROPIC_API_KEY`, an isolated
module prepends a short synthesis. It is instructed to use only the deterministic memo and
**never invent data**; any failure silently falls back to the deterministic memo. The Claude
Max subscription does not power this — it needs an API key, and the system is fully usable
without it.

---

## Tests

```bash
pytest -q
```

Tests run **fully offline** (network is disabled in `conftest.py`) and cover scoring, sizing,
portfolio analytics, reports, backtest, schemas, and the **broker-automation guardrails**
(a test fails if any source file contains order-execution or credential-capture terms).

---

## Project structure

```
src/
  config.py            # config.yaml + .env loader
  data/                # provider interface, mock engine, Börsdata/EODHD/Finnhub, FX, news
  universe/            # Sweden / EU / US lists + liquidity filters
  models/schemas.py    # Pydantic schemas (missing = None, never invented)
  scoring/             # fundamentals, technicals, catalysts, risk, composite
  portfolio/           # CSV import, SEK whole-share sizing, opportunity cost
  reports/             # citation manager, templates, memo generator (+ optional LLM)
  backtest/            # momentum backtest + walk-forward
  alerts/              # optional Telegram / email
  dashboard/           # Streamlit app (app.py + pages)
  storage/             # SQLite cache, watchlist, portfolio, memo history
  utils/               # logging (network audit), dates, currency
tests/                 # pytest suite (offline)
```

---

## Limitations & honesty

- Mock data is **synthetic** and for UI/demo only — clearly flagged everywhere.
- Backtest is **technical/momentum only** (fundamentals are not point-in-time) and the
  universe is **survivorship-biased**. Treat it as a signal sanity check, not a track record.
- Real provider field mappings are conservative; verify against your live API responses.
- Data may be delayed. **Always verify before acting. You place all orders manually.**

**This is not personal financial advice.**

---

## Roadmap

- **Phase 1 ✅** — structure, config/db/schemas/logging, Börsdata + global client, CSV import,
  deterministic scoring, dashboard (Opportunities + Deep Dive).
- **Phase 2 ✅** — news/catalysts, citations, memo generator, Portfolio Review + Risk, alerts.
- **Phase 3 ✅ (initial)** — backtest + walk-forward, EU/US expansion, richer technicals,
  optional LLM memo.
- **Phase 4 ✅** — keyless live data (Yahoo), and the **always-on engine**: scheduled
  SE/EU/US scanner, state-based signal de-dup, Telegram + email alerts, morning/close
  digests, Alerts dashboard page, and Docker/Fly deploy.
- **Phase 5 ✅** — **crypto sleeve** (separate scoring model + discovery + holding signals),
  an **Apple-inspired UI** (real-button navigation, SF Pro typography), portfolio **pulse**
  alerts, and **automatic rotating SQLite backups** on every save.
- **Next** — point-in-time fundamentals, market-holiday calendar, per-signal config in the
  UI, optional intraday-interval prices, FastAPI backend.
