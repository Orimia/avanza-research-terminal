"""Always-on engine: scheduled scanner + state-based alerting.

The engine refreshes SE/EU/US data on a schedule, detects *actionable
transitions* (new buys, holding sell/trim, stop/take-profit hits, big moves,
breakouts, RSI extremes, imminent earnings), de-duplicates them against stored
state so you only get NEW signals, and pushes Telegram + email alerts plus a
morning and post-close digest. Research only — it never trades.
"""
