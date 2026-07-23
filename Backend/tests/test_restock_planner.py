import pytest

from app.models import CountEntry, CountSession, Restaurant
from app.services.restock_planner_service import RestockPlannerError, build_restock_plan


def _csv(text: str) -> bytes:
    return text.strip().encode("utf-8")


def _count_with_entries(entries: list[CountEntry]) -> CountSession:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    count = CountSession(id=1, restaurant_id=1, status="completed", restaurant=restaurant)
    count.entries = entries
    for index, entry in enumerate(entries, start=1):
        entry.id = index
        entry.count_session_id = 1
        entry.count_session = count
    return count


def test_basic_sales_to_weekly_purchase_plan() -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ]
    )

    result = build_restock_plan(
        count,
        _csv(
            """
            item_name,quantity_sold,date
            Chicken Sandwich,400,2026-07-01
            """
        ),
        _csv(
            """
            menu_item,ingredient_name,quantity_per_item,unit
            Chicken Sandwich,Chicken Breast,0.25,pounds
            """
        ),
    )

    assert result["summary"] == {
        "items_forecasted": 1,
        "suggested_purchases": 1,
        "needs_review": 0,
        "safety_buffer_percent": 10,
    }
    assert result["purchase_plan"][0] == {
        "ingredient": "Chicken Breast",
        "projected_need": 27.5,
        "current_stock": 10,
        "current_stock_unit": "pounds",
        "suggested_purchase": 17.5,
        "unit": "pounds",
        "status": "Ready",
        "reason": "Based on 100 projected Chicken Sandwich sales and 0.25 pounds per item.",
    }


def test_same_ingredient_across_menu_items_sums_and_applies_buffer() -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Burger Buns",
                normalized_item_name="burger buns",
                quantity=48,
                unit="buns",
                status="Clean",
            )
        ]
    )

    result = build_restock_plan(
        count,
        _csv(
            """
            item_name,quantity_sold
            Chicken Sandwich,400
            Burger,300
            """
        ),
        _csv(
            """
            menu_item,ingredient_name,quantity_per_item,unit
            Chicken Sandwich,Burger Buns,1,buns
            Burger,Burger Buns,1,buns
            """
        ),
    )

    row = result["purchase_plan"][0]
    assert row["ingredient"] == "Burger Buns"
    assert row["projected_need"] == 192.5
    assert row["current_stock"] == 48
    assert row["suggested_purchase"] == 144.5
    assert row["status"] == "Ready"


def test_suggested_purchase_never_goes_negative() -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Whole Milk",
                normalized_item_name="whole milk",
                quantity=40,
                unit="gallons",
                status="Clean",
            )
        ]
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nLatte,200"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nLatte,Whole Milk,0.05,gallons"),
    )

    row = result["purchase_plan"][0]
    assert row["projected_need"] == 2.75
    assert row["suggested_purchase"] == 0
    assert row["status"] == "Ready"


def test_unknown_stock_row_is_included_for_review() -> None:
    result = build_restock_plan(
        _count_with_entries([]),
        _csv("item_name,quantity_sold\nLatte,200"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nLatte,Whole Milk,0.05,gallons"),
    )

    row = result["purchase_plan"][0]
    assert row["ingredient"] == "Whole Milk"
    assert row["current_stock"] is None
    assert row["suggested_purchase"] == 2.75
    assert row["status"] == "Stock Unknown"
    assert result["summary"]["needs_review"] == 1


def test_unit_mismatch_is_flagged_without_subtracting_stock() -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=3,
                unit="cases",
                status="Clean",
            )
        ]
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
    )

    row = result["purchase_plan"][0]
    assert row["current_stock"] == 3
    assert row["current_stock_unit"] == "cases"
    assert row["suggested_purchase"] == 27.5
    assert row["status"] == "Unit Mismatch"
    assert "did not safely subtract" in row["reason"]


def test_missing_sales_columns_returns_clear_error() -> None:
    with pytest.raises(RestockPlannerError, match="Missing required sales columns: quantity_sold"):
        build_restock_plan(
            _count_with_entries([]),
            _csv("item_name\nChicken Sandwich"),
            _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        )


def test_missing_recipe_columns_returns_clear_error() -> None:
    with pytest.raises(RestockPlannerError, match="Missing required recipe columns: quantity_per_item"):
        build_restock_plan(
            _count_with_entries([]),
            _csv("item_name,quantity_sold\nChicken Sandwich,400"),
            _csv("menu_item,ingredient_name,unit\nChicken Sandwich,Chicken Breast,pounds"),
        )
