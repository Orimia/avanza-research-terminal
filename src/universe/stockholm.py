"""Nasdaq Stockholm universe (Large/Mid/Small cap, liquid names).

Tickers use Börsdata/Avanza-style class suffixes (e.g. ``VOLV-B``) and the
``ST`` exchange code. This is a curated liquid set, not the full exchange.
"""

STOCKHOLM: list[tuple[str, str]] = [
    ("VOLV-B", "ST"), ("ERIC-B", "ST"), ("HM-B", "ST"), ("ATCO-A", "ST"),
    ("ATCO-B", "ST"), ("INVE-B", "ST"), ("SEB-A", "ST"), ("SHB-A", "ST"),
    ("SWED-A", "ST"), ("AZN", "ST"), ("ASSA-B", "ST"), ("SAND", "ST"),
    ("EVO", "ST"), ("SINCH", "ST"), ("NIBE-B", "ST"), ("ALFA", "ST"),
    ("BOL", "ST"), ("ELUX-B", "ST"), ("ESSITY-B", "ST"), ("GETI-B", "ST"),
    ("HEXA-B", "ST"), ("KINV-B", "ST"), ("LUND-B", "ST"), ("SKF-B", "ST"),
    ("SCA-B", "ST"), ("SWMA", "ST"), ("TEL2-B", "ST"), ("TELIA", "ST"),
    ("VOLCAR-B", "ST"), ("EPI-A", "ST"), ("EQT", "ST"), ("INDU-C", "ST"),
    ("SAGA-B", "ST"), ("BALD-B", "ST"), ("CAST", "ST"), ("FABG", "ST"),
    ("LIFCO-B", "ST"), ("LATO-B", "ST"), ("ADDT-B", "ST"), ("INDT", "ST"),
    ("NDA-SE", "ST"), ("DOM", "ST"), ("BILL", "ST"), ("TREL-B", "ST"),
    ("SECU-B", "ST"), ("THULE", "ST"), ("MTRS", "ST"), ("VITR", "ST"),
    ("EKTA-B", "ST"), ("SOBI", "ST"), ("BEIJ-B", "ST"), ("CamX", "ST"),
    ("NCC-B", "ST"), ("PEAB-B", "ST"), ("SKA-B", "ST"), ("HUSQ-B", "ST"),
    ("AAK", "ST"), ("DUST", "ST"), ("MCOV-B", "ST"), ("SAVE", "ST"),
]
