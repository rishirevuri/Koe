from app.services.partial_quantity_service import parse_partial_quantity


def test_half_empty_bottle_total() -> None:
    result = parse_partial_quantity("3 bottles olive oil, one half empty", 3, "bottles")
    assert result.quantity == 2.5
    assert result.unit == "bottles"
    assert result.partial_detail == "2 full bottles + 1 half bottle"
    assert result.needs_review is False


def test_plus_half_case_total() -> None:
    result = parse_partial_quantity("2 cases plus half a case")
    assert result.quantity == 2.5
    assert result.unit == "cases"


def test_three_quarters_full_total() -> None:
    result = parse_partial_quantity("4 tubs sauce, one three quarters full", 4, "tubs")
    assert result.quantity == 3.75
    assert result.partial_detail == "3 full tubs + 1 three quarters tub"


def test_vague_partial_needs_review() -> None:
    result = parse_partial_quantity("5 bottles, one almost empty", 5, "bottles")
    assert result.quantity == 5
    assert result.needs_review is True
    assert result.review_reason == "Vague partial quantity: almost empty"
