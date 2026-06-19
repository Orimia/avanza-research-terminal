"""Major liquid European names (ex-Nordic).

Uses the internal ``EU`` exchange code; the EODHD client maps each to the right
venue suffix. Curated toward quality large/mid caps across semis, defense,
industrials, energy, banks, luxury, healthcare and software.
"""

EU: list[tuple[str, str]] = [
    ("ASML", "EU"), ("SAP", "EU"), ("SIE", "EU"), ("MC", "EU"),      # LVMH
    ("OR", "EU"), ("AIR", "EU"), ("SU", "EU"), ("TTE", "EU"),         # L'Oreal, Airbus, Schneider, TotalEnergies
    ("RMS", "EU"), ("SAN", "EU"), ("BNP", "EU"), ("ALV", "EU"),       # Hermes, Sanofi, BNP, Allianz
    ("DTE", "EU"), ("BAS", "EU"), ("BAYN", "EU"), ("IFX", "EU"),      # Deutsche Telekom, BASF, Bayer, Infineon
    ("ADS", "EU"), ("MBG", "EU"), ("BMW", "EU"), ("VOW3", "EU"),      # Adidas, Mercedes, BMW, VW
    ("ENEL", "EU"), ("ENI", "EU"), ("ISP", "EU"), ("UCG", "EU"),      # Enel, ENI, Intesa, UniCredit
    ("STLAM", "EU"), ("RACE", "EU"), ("PRX", "EU"), ("ASRNL", "EU"),  # Stellantis, Ferrari, Prosus
    ("AD", "EU"), ("PHIA", "EU"), ("INGA", "EU"), ("DG", "EU"),       # Ahold, Philips, ING, Vinci
    ("EL", "EU"), ("KER", "EU"), ("CAP", "EU"), ("DSY", "EU"),        # EssilorLuxottica, Kering, Capgemini, Dassault
    ("RHM", "EU"), ("MTX", "EU"), ("HEN3", "EU"), ("MUV2", "EU"),     # Rheinmetall, MTU, Henkel, Munich Re
]
