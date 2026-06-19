"""Avanza CSV adapter, paste parser, number parsing, format auto-detection."""
from src.portfolio.import_avanza_csv import (
    _sv_float,
    parse_any,
    parse_avanza_export,
    parse_paste,
)


def test_sv_float_european_numbers():
    assert _sv_float("1 234,56") == 1234.56
    assert _sv_float("319,40") == 319.40
    assert _sv_float("1.234,56") == 1234.56
    assert _sv_float("12,5%") == 12.5
    assert _sv_float("—") is None
    assert _sv_float("") is None


def test_parse_paste():
    hs = parse_paste("VOLV-B 40 245\nNVDA 8 95 US USD\n# junk line")
    assert len(hs) == 2
    assert hs[0].ticker == "VOLV-B" and hs[0].shares == 40 and hs[0].average_cost == 245
    assert hs[1].exchange == "US" and hs[1].currency == "USD"


def test_parse_avanza_export_swedish_columns():
    csv = ("Namn;Kortnamn;Volym;GAV;Valuta\n"
           "AB Volvo;VOLV B;40;245,50;SEK\n"
           "NVIDIA Corp;NVDA;8;95,00;USD\n"
           "Sparkonto;;;;SEK\n")  # cash row -> skipped (no volume)
    hs = parse_avanza_export(csv)
    syms = {h.ticker for h in hs}
    assert "VOLV-B" in syms and "NVDA" in syms and len(hs) == 2
    volv = next(h for h in hs if h.ticker == "VOLV-B")
    assert volv.shares == 40 and abs(volv.average_cost - 245.50) < 1e-6 and volv.exchange == "ST"
    nvda = next(h for h in hs if h.ticker == "NVDA")
    assert nvda.currency == "USD" and nvda.exchange == "US"


def test_parse_avanza_derives_cost_from_total():
    # only total acquisition value present -> per-share cost = total / shares
    csv = "Namn;Kortnamn;Antal;Anskaffningsvärde;Valuta\nInvestor;INVE B;10;2000,00;SEK\n"
    hs = parse_avanza_export(csv)
    assert len(hs) == 1 and abs(hs[0].average_cost - 200.0) < 1e-6


def test_parse_any_format_detection():
    _, fmt_av = parse_any("Namn;Kortnamn;Volym;GAV;Valuta\nAB Volvo;VOLV B;40;245,50;SEK\n")
    assert fmt_av == "Avanza export"
    _, fmt_paste = parse_any("VOLV-B 40 245")
    assert fmt_paste == "pasted list"
    native = "ticker,exchange,shares,average_cost,currency\nVOLV-B,ST,40,245,SEK\n"
    hs, fmt_native = parse_any(native)
    assert fmt_native == "native CSV" and hs[0].ticker == "VOLV-B"
