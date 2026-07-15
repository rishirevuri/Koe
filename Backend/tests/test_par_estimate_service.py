from app.services.par_estimate_service import estimate_par_status


def test_lemons_under_demo_par_are_critical() -> None:
    estimate = estimate_par_status(item_name="lemons", quantity=10, unit="individual", status="Clean")

    assert estimate["par_status"] == "critical"
    assert estimate["estimated_par_quantity"] == 30
    assert estimate["par_unit"] == "individual"
    assert estimate["is_demo_estimate"] is True


def test_eggs_above_demo_par_are_sufficient() -> None:
    estimate = estimate_par_status(item_name="eggs", quantity=198, unit="eggs", status="Clean")

    assert estimate["par_status"] == "sufficient"
    assert estimate["estimated_par_quantity"] == 120


def test_napkins_half_case_is_critical() -> None:
    estimate = estimate_par_status(item_name="napkins", quantity=0.5, unit="cases", status="Clean")

    assert estimate["par_status"] == "critical"
    assert estimate["estimated_par_quantity"] == 2
    assert estimate["par_unit"] == "cases"


def test_null_quantity_is_unknown() -> None:
    estimate = estimate_par_status(item_name="limes", quantity=None, unit="individual", status="Clean")

    assert estimate["par_status"] == "unknown"
    assert estimate["estimated_par_quantity"] is None
    assert "Quantity is missing" in estimate["par_reason"]


def test_tomato_sauce_below_demo_par_is_low() -> None:
    estimate = estimate_par_status(item_name="tomato sauce", quantity=8, unit="cans", status="Clean")

    assert estimate["par_status"] == "low"
    assert estimate["estimated_par_quantity"] == 12
    assert estimate["par_unit"] == "cans"


def test_paper_cups_above_demo_par_are_sufficient() -> None:
    estimate = estimate_par_status(item_name="paper cups", quantity=1000, unit="cups", status="Clean")

    assert estimate["par_status"] == "sufficient"
    assert estimate["estimated_par_quantity"] == 500


def test_incompatible_unit_is_unknown() -> None:
    estimate = estimate_par_status(item_name="lemons", quantity=10, unit="cases", status="Clean")

    assert estimate["par_status"] == "unknown"
    assert estimate["estimated_par_quantity"] is None
    assert "cannot be safely compared" in estimate["par_reason"]


def test_needs_review_status_is_unknown() -> None:
    estimate = estimate_par_status(item_name="lemons", quantity=10, unit="individual", status="Needs Review")

    assert estimate["par_status"] == "unknown"
    assert estimate["estimated_par_quantity"] is None
    assert "Review item status" in estimate["par_reason"]
