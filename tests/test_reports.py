"""Memo generation contains required disclosures and sections."""
from src.data.provider import get_stock_data
from src.dashboard import ui  # noqa: F401  (ensures package import path is sane)
from src.reports.memo_generator import generate_memo
from src.scoring.composite import build_recommendation


def test_memo_has_disclaimer_sections_and_mock_flag():
    data = get_stock_data("VOLV-B", "ST")
    fx = {"SEKSEK": 1.0}
    rec = build_recommendation(data, fx)
    memo = generate_memo(data, rec)
    assert "This is not personal financial advice." in memo
    assert "MOCK DATA" in memo                     # offline -> synthetic
    for section in ["A. Executive summary", "E. Bear case", "I. Self-attack",
                    "Institutional lenses", "Sources"]:
        assert section in memo
    # memo states the guardrail explicitly
    assert "no broker login, no orders" in memo.lower()
