"""US universe — current, liquid, DIVERSE leaders across the thesis sectors.

Ordered so the screener (which fetches the first ``screener_limits.us`` names)
sees a spread of AI infra, semis, software, fintech, energy, defense, healthcare
and consumer — not just mega-cap tech. Penny/illiquid names excluded.
"""

US: list[tuple[str, str]] = [
    # mega-cap / AI platforms
    ("NVDA", "US"), ("MSFT", "US"), ("AAPL", "US"), ("GOOGL", "US"),
    ("AMZN", "US"), ("META", "US"), ("AVGO", "US"), ("TSM", "US"),
    # AI infrastructure / semis
    ("AMD", "US"), ("ARM", "US"), ("MU", "US"), ("ANET", "US"),
    ("VRT", "US"), ("LRCX", "US"), ("KLAC", "US"), ("AMAT", "US"), ("MRVL", "US"),
    # software / data
    ("ORCL", "US"), ("PLTR", "US"), ("NOW", "US"), ("CRM", "US"),
    ("PANW", "US"), ("CRWD", "US"), ("DDOG", "US"), ("APP", "US"), ("NFLX", "US"),
    # fintech / financials
    ("JPM", "US"), ("V", "US"), ("MA", "US"), ("GS", "US"), ("KKR", "US"),
    ("BRK-B", "US"), ("COIN", "US"), ("HOOD", "US"), ("NU", "US"),
    # energy / power (AI-electricity theme)
    ("XOM", "US"), ("CVX", "US"), ("CEG", "US"), ("VST", "US"), ("GEV", "US"),
    # defense / industrials
    ("LMT", "US"), ("RTX", "US"), ("GD", "US"), ("GE", "US"), ("AXON", "US"),
    # healthcare
    ("LLY", "US"), ("UNH", "US"), ("ISRG", "US"),
    # consumer compounders
    ("COST", "US"), ("WMT", "US"), ("MELI", "US"),
]
