from datetime import datetime, timezone

import pytest

from app.models import CountEntry, CountSession, Restaurant
from app.services import restock_planner_service
from app.services.restock_planner_service import RestockPlannerError, build_restock_plan, normalize_sales_csv


def _csv(text: str) -> bytes:
    return text.strip().encode("utf-8")


def _count_with_entries(entries: list[CountEntry], *, count_id: int = 1, completed_at: datetime | None = None) -> CountSession:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    count = CountSession(
        id=count_id,
        restaurant_id=1,
        status="completed",
        completed_at=completed_at or datetime(2026, 7, 20, tzinfo=timezone.utc),
        restaurant=restaurant,
    )
    count.entries = entries
    for index, entry in enumerate(entries, start=1):
        entry.id = index
        entry.count_session_id = count_id
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

    assert result["summary"]["items_forecasted"] == 1
    assert result["summary"]["suggested_purchases"] == 1
    assert result["summary"]["needs_review"] == 0
    assert result["summary"]["safety_buffer_percent"] == 10
    assert result["summary"]["history_counts_used"] == 0
    assert result["summary"]["history_quality"] == "none"
    assert result["summary"]["history_interval_notes"] == []
    assert result["summary"]["forecast_mode"] == "deterministic_recipe_only"
    assert result["summary"]["planner_source"] == "deterministic_fallback"
    row = result["purchase_plan"][0]
    assert row["ingredient"] == "Chicken Breast"
    assert row["projected_need"] == 25
    assert row["adjusted_need"] == 25
    assert row["current_stock"] == 10
    assert row["current_stock_unit"] == "pounds"
    assert row["suggested_purchase"] == 17.5
    assert row["unit"] == "pounds"
    assert row["usage_multiplier"] is None
    assert row["action"] == "buy"
    assert row["confidence"] == "Medium"
    assert row["status"] == "Limited History"
    assert row["reason"] == "Based on sales and recipe usage only from 100 projected Chicken Sandwich sales and 0.25 pounds per item. Add previous counts to learn actual depletion."


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
    assert row["projected_need"] == 175
    assert row["adjusted_need"] == 175
    assert row["current_stock"] == 48
    assert row["suggested_purchase"] == 144.5
    assert row["status"] == "Limited History"


def test_sales_exact_columns_parse_without_claude(monkeypatch) -> None:
    def fail_if_called(csv_text: str) -> dict:
        raise AssertionError("Claude should not be used for exact sales columns")

    monkeypatch.setattr(restock_planner_service, "normalize_sales_report_with_claude", fail_if_called)

    result = normalize_sales_csv(_csv("item_name,quantity_sold\nChicken Sandwich,400"), use_claude=True)

    assert result.source == "direct"
    assert result.rows[0].item_name == "Chicken Sandwich"
    assert result.rows[0].quantity_sold == 400


def test_sales_alias_columns_parse_directly_and_ignore_summary_rows() -> None:
    result = normalize_sales_csv(
        _csv(
            """
            Product Name,Qty Sold,Business Date
            Crispy Chicken Sandwich,120,2026-07-20
            Subtotal,120,2026-07-20
            Tax,10,2026-07-20
            """
        ),
        use_claude=False,
    )

    assert result.source == "direct"
    assert result.columns_detected == {
        "item_name": "Product Name",
        "quantity_sold": "Qty Sold",
        "date": "Business Date",
    }
    assert len(result.rows) == 1
    assert result.rows[0].item_name == "Crispy Chicken Sandwich"
    assert result.rows[0].quantity_sold == 120
    assert result.rows[0].date == "2026-07-20"
    assert result.warnings


def test_sales_menu_item_items_sold_aliases_and_duplicates_merge() -> None:
    result = normalize_sales_csv(
        _csv(
            """
            Menu Item,Items Sold
            Classic Cheeseburger,50
            Classic Cheeseburger,45
            Iced Latte,180
            """
        )
    )

    rows = {row.item_name: row for row in result.rows}
    assert rows["Classic Cheeseburger"].quantity_sold == 95
    assert rows["Iced Latte"].quantity_sold == 180


def test_claude_sales_normalization_success_feeds_restock_planner(monkeypatch) -> None:
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

    def mock_normalize(csv_text: str) -> dict:
        assert "POS Item" in csv_text
        return {
            "sales_rows": [
                {
                    "item_name": "Chicken Sandwich",
                    "quantity_sold": 400,
                    "confidence": "High",
                    "source_hint": "Matched from POS Item and Units columns",
                }
            ],
            "warnings": [{"message": "Ignored modifier rows."}],
            "normalization_summary": {
                "rows_read": 2,
                "sales_rows_extracted": 1,
                "columns_detected": {"item_name": "POS Item", "quantity_sold": "Units", "date": None},
            },
        }

    monkeypatch.setattr(restock_planner_service, "normalize_sales_report_with_claude", mock_normalize)

    result = build_restock_plan(
        count,
        _csv("POS Item,Units\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["sales_normalization"]["source"] == "claude"
    assert result["sales_normalization"]["sales_rows_extracted"] == 1
    assert result["sales_normalization"]["preview_rows"][0]["item_name"] == "Chicken Sandwich"
    assert result["purchase_plan"][0]["projected_need"] == 25


def test_malformed_claude_sales_normalization_returns_friendly_error(monkeypatch) -> None:
    monkeypatch.setattr(restock_planner_service, "normalize_sales_report_with_claude", lambda csv_text: {"sales_rows": "bad"})

    with pytest.raises(RestockPlannerError, match="Koe could not read sales quantities from this file"):
        normalize_sales_csv(_csv("POS Item,Units\nChicken Sandwich,400"), use_claude=True)


def test_claude_sales_normalization_with_no_usable_rows_returns_friendly_error(monkeypatch) -> None:
    monkeypatch.setattr(
        restock_planner_service,
        "normalize_sales_report_with_claude",
        lambda csv_text: {"sales_rows": [{"item_name": "Subtotal", "quantity_sold": "not a number"}]},
    )

    with pytest.raises(RestockPlannerError, match="Koe could not read sales quantities from this file"):
        normalize_sales_csv(_csv("POS Item,Units\nSubtotal,abc"), use_claude=True)


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
    assert row["projected_need"] == 2.5
    assert row["adjusted_need"] == 2.5
    assert row["suggested_purchase"] == 0
    assert row["status"] == "Limited History"


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
    assert "cannot safely subtract" in row["reason"]


def test_previous_count_depletion_creates_adaptive_multiplier() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=130,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
    )

    row = result["purchase_plan"][0]
    assert result["summary"]["forecast_mode"] == "deterministic_adaptive"
    assert result["summary"]["history_counts_used"] == 1
    assert result["summary"]["history_quality"] == "basic"
    assert result["summary"]["history_interval_notes"][0]["quality"] == "ideal"
    assert result["summary"]["history_interval_notes"][0]["days_between"] == 5
    assert row["projected_need"] == 25
    assert row["usage_multiplier"] == 1.2
    assert row["adjusted_need"] == 30
    assert row["suggested_purchase"] == 23
    assert row["status"] == "Ready"
    assert result["learning_notes"]


def test_negative_depletion_is_ignored_and_flagged_for_review() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=20,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
    )

    row = result["purchase_plan"][0]
    assert result["summary"]["forecast_mode"] == "deterministic_recipe_only"
    assert result["summary"]["history_counts_used"] == 0
    assert row["usage_multiplier"] is None
    assert row["status"] == "Needs Review"
    assert "ignored that interval" in result["learning_notes"][0]["note"]


def test_previous_count_less_than_three_days_old_marks_weak_history() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
        completed_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=130,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
        completed_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
    )

    assert result["summary"]["forecast_mode"] == "deterministic_adaptive"
    assert result["summary"]["history_quality"] == "weak"
    assert result["summary"]["history_interval_notes"] == [
        {
            "previous_count_id": 1,
            "days_between": 1,
            "quality": "weak_short",
            "note": "This count is very close to the current count, so history confidence is limited.",
        }
    ]


def test_previous_count_more_than_twenty_one_days_old_marks_weak_history() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
        completed_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=130,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
        completed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
    )

    assert result["summary"]["forecast_mode"] == "deterministic_adaptive"
    assert result["summary"]["history_quality"] == "weak"
    assert result["summary"]["history_interval_notes"][0]["days_between"] == 30
    assert result["summary"]["history_interval_notes"][0]["quality"] == "weak_long"


def test_usage_multiplier_is_clamped_for_extreme_history() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=500,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
    )

    row = result["purchase_plan"][0]
    assert row["usage_multiplier"] == 2.5
    assert row["adjusted_need"] == 62.5
    assert row["status"] == "Needs Review"
    assert result["summary"]["needs_review"] == 1


def test_multiple_previous_counts_use_weighted_average_multiplier() -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=3,
        completed_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    recent_previous = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=110,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    older_previous = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=210,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
        completed_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [older_previous, recent_previous],
    )

    row = result["purchase_plan"][0]
    assert row["usage_multiplier"] == 1.46
    assert row["adjusted_need"] == 36.49
    assert row["status"] == "Ready"
    assert result["summary"]["history_counts_used"] == 2
    assert result["summary"]["history_quality"] == "strong"


def test_qualitative_current_stock_is_not_used_in_math() -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Peanut Butter",
                normalized_item_name="peanut butter",
                quantity=None,
                quantity_label="Mostly full",
                unit="bucket",
                status="Needs Review",
            )
        ]
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nPB Sandwich,80"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nPB Sandwich,Peanut Butter,0.1,bucket"),
    )

    row = result["purchase_plan"][0]
    assert row["current_stock"] is None
    assert row["suggested_purchase"] == 2.2
    assert row["status"] == "Needs Review"
    assert "qualitative quantity" in row["reason"]


def _claude_chicken_row() -> dict:
    return {
        "ingredient": "Chicken Breast",
        "suggested_purchase": 30,
        "unit": "pounds",
        "action": "buy",
        "status": "Ready",
        "confidence": "High",
        "projected_need": 25,
        "adjusted_need": 33,
        "current_stock": 10,
        "usage_signal": "high",
        "history_signal": "limited_history",
        "risk_signal": "stockout_risk",
        "reason": "Current stock is low against menu demand.",
    }


def test_claude_row_with_exact_ingredient_key_matches(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Ground Beef",
                normalized_item_name="ground beef",
                quantity=5,
                unit="pounds",
                status="Clean",
            )
        ]
    )
    captured: dict = {}

    def mock_generate(evidence_packet: dict) -> dict:
        captured["ingredient_key"] = evidence_packet["ingredients"][0]["ingredient_key"]
        return {
            "purchase_plan": [
                {
                    "ingredient_key": "ground_beef",
                    "ingredient": "Ground Beef",
                    "suggested_purchase": 12,
                    "unit": "pounds",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "Medium",
                    "reason": "Ground beef needs replenishment.",
                }
            ]
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nBurger,200"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nBurger,Ground Beef,0.25,pounds"),
        use_claude=True,
    )

    assert captured["ingredient_key"] == "ground_beef"
    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient_key"] == "ground_beef"
    assert result["purchase_plan"][0]["ingredient"] == "Ground Beef"


def test_claude_planner_success_uses_evidence_and_returns_adaptive_plan(monkeypatch) -> None:
    current_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=2,
    )
    previous_count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=130,
                unit="pounds",
                status="Clean",
            )
        ],
        count_id=1,
    )
    captured: dict = {}

    def mock_generate(evidence_packet: dict) -> dict:
        captured["evidence_packet"] = evidence_packet
        return {
            "summary": {"forecast_mode": "claude_adaptive", "overall_note": "History was useful."},
            "purchase_plan": [
                {
                    "ingredient": "Chicken Breast",
                    "suggested_purchase": 30,
                    "unit": "pounds",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "High",
                    "projected_need": 25,
                    "adjusted_need": 33,
                    "current_stock": 10,
                    "usage_signal": "high",
                    "history_signal": "depletes_faster_than_expected",
                    "risk_signal": "stockout_risk",
                    "reason": "Past counts show chicken breast disappears faster than recipe demand alone.",
                }
            ],
            "learning_notes": [{"ingredient": "Chicken Breast", "note": "Chicken breast runs above recipe math."}],
            "review_warnings": [],
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        current_count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        [previous_count],
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["summary"]["forecast_mode"] == "claude_adaptive"
    assert result["summary"]["history_counts_used"] == 1
    assert result["summary"]["history_quality"] == "weak"
    assert result["summary"]["overall_note"] == "History was useful."
    assert result["purchase_plan"][0]["action"] == "buy"
    assert result["purchase_plan"][0]["confidence"] == "High"
    assert result["learning_notes"][0]["note"] == "Chicken breast runs above recipe math."
    evidence = captured["evidence_packet"]["ingredients"][0]
    assert evidence["ingredient_name"] == "Chicken Breast"
    assert evidence["previous_counts"][0]["quantity"] == 130
    assert evidence["deterministic_signals"]["has_usable_history"] is True
    assert captured["evidence_packet"]["history_quality"] == "weak"
    assert captured["evidence_packet"]["history_interval_notes"][0]["quality"] == "weak_short"


def test_claude_recipe_only_mode_without_previous_counts(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Whole Milk",
                normalized_item_name="whole milk",
                quantity=1,
                unit="gallons",
                status="Clean",
            )
        ]
    )

    def mock_generate(evidence_packet: dict) -> dict:
        assert evidence_packet["previous_count_ids"] == []
        return {
            "summary": {"forecast_mode": "claude_recipe_only", "overall_note": "Recipe-only forecast."},
            "purchase_plan": [
                {
                    "ingredient": "Whole Milk",
                    "suggested_purchase": 2,
                    "unit": "gallons",
                    "action": "buy",
                    "status": "Limited History",
                    "confidence": "Medium",
                    "projected_need": 2.5,
                    "adjusted_need": 2.5,
                    "current_stock": 1,
                    "usage_signal": "unknown",
                    "history_signal": "limited_history",
                    "risk_signal": "balanced",
                    "reason": "Based on sales and menu usage only.",
                }
            ],
            "learning_notes": [],
            "review_warnings": [],
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nLatte,200"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nLatte,Whole Milk,0.05,gallons"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["summary"]["forecast_mode"] == "claude_recipe_only"
    assert result["summary"]["history_quality"] == "none"
    assert result["purchase_plan"][0]["status"] == "Limited History"


@pytest.mark.parametrize(
    "claude_payload",
    [
        {"summary": {"forecast_mode": "claude_recipe_only"}, "purchase_plan": {"items": [_claude_chicken_row()]}},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "purchase_plan": {"rows": [_claude_chicken_row()]}},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "items": [_claude_chicken_row()]},
        [_claude_chicken_row()],
        {"summary": {"forecast_mode": "claude_recipe_only"}, "recommendations": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "restock_plan": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "purchase_recommendations": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "suggested_purchases": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "draft_purchase_plan": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "plan": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "plan": {"items": [_claude_chicken_row()]}},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "draft_purchase_plan": {"recommendations": [_claude_chicken_row()]}},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "rows": [_claude_chicken_row()]},
        {"summary": {"forecast_mode": "claude_recipe_only"}, "data": [_claude_chicken_row()]},
    ],
)
def test_claude_purchase_plan_recoverable_shapes_are_repaired(monkeypatch, claude_payload) -> None:
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

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", lambda evidence_packet: claude_payload)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient"] == "Chicken Breast"
    assert result["purchase_plan"][0]["suggested_purchase"] == 30


def test_claude_sectioned_buy_hold_review_shape_is_combined(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=10,
                unit="pounds",
                status="Clean",
            ),
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=20,
                unit="count",
                status="Clean",
            ),
        ]
    )

    hold_row = {
        **_claude_chicken_row(),
        "ingredient": "Tomatoes",
        "suggested_purchase": 0,
        "unit": "count",
        "status": "Ready",
        "confidence": "Medium",
        "reason": "Current stock covers the projected need.",
    }

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {"buy": [_claude_chicken_row()], "hold": [hold_row], "review": []},
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400\nSalad,20"),
        _csv(
            """
            menu_item,ingredient_name,quantity_per_item,unit
            Chicken Sandwich,Chicken Breast,0.25,pounds
            Salad,Tomatoes,0.25,count
            """
        ),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    rows = {row["ingredient"]: row for row in result["purchase_plan"]}
    assert rows["Chicken Breast"]["action"] == "buy"
    assert rows["Tomatoes"]["action"] == "hold"


def test_claude_row_field_aliases_are_normalized(monkeypatch) -> None:
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

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "recommendations": [
                {
                    "item_name": "Chicken Breast",
                    "recommended_quantity": "30 pounds",
                    "purchase_unit": "pounds",
                    "recommendation": "buy",
                    "review_status": "Ready",
                    "confidence_level": "High",
                    "projected": 25,
                    "adjusted": 33,
                    "stock_on_hand": 10,
                    "rationale": "Demand and current stock support a purchase.",
                }
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    row = result["purchase_plan"][0]
    assert result["summary"]["planner_source"] == "claude"
    assert row["ingredient"] == "Chicken Breast"
    assert row["suggested_purchase"] == 30
    assert row["reason"] == "Demand and current stock support a purchase."
    assert row["projected_need"] == 25
    assert row["adjusted_need"] == 33


def test_claude_singular_plural_name_mismatch_matches(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken breasts",
                normalized_item_name="chicken breasts",
                quantity=10,
                unit="pounds",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "purchase_plan": [
                {
                    **_claude_chicken_row(),
                    "ingredient": "Chicken Breast",
                }
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken breasts,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient"] == "Chicken breasts"
    assert result["purchase_plan"][0]["ingredient_key"] == "chicken_breasts"


def test_claude_minor_name_variation_matches(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Paper Cup",
                normalized_item_name="paper cup",
                quantity=100,
                unit="cups",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "purchase_plan": [
                {
                    "ingredient": "Paper Cups",
                    "suggested_purchase": 500,
                    "unit": "cups",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "Medium",
                    "reason": "Cup usage is above current stock.",
                }
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nIced Tea,300"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nIced Tea,Paper Cup,1,cups"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient"] == "Paper Cup"
    assert result["purchase_plan"][0]["suggested_purchase"] == 500


def test_claude_unknown_ingredient_is_kept_as_review(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=2,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "purchase_plan": [
                {
                    "ingredient": "Fake Vendor Item",
                    "suggested_purchase": 10,
                    "unit": "cases",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "High",
                    "reason": "This row should need review.",
                }
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nSalad,40"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nSalad,Tomatoes,0.1,boxes"),
        use_claude=True,
    )

    row = result["purchase_plan"][0]
    assert result["summary"]["planner_source"] == "claude"
    assert row["ingredient"] == "Fake Vendor Item"
    assert row["suggested_purchase"] is None
    assert row["action"] == "review"
    assert row["status"] == "Needs Review"
    assert row["confidence"] == "Low"
    assert "could not confidently match" in row["reason"]


def test_claude_mixed_matched_and_unknown_rows_remain_claude(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=2,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "purchase_plan": [
                {
                    "ingredient_key": "tomatoes",
                    "ingredient": "Tomatoes",
                    "suggested_purchase": 3,
                    "unit": "boxes",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "Medium",
                    "reason": "Tomatoes are low.",
                },
                {
                    "ingredient": "Fake Vendor Item",
                    "suggested_purchase": 10,
                    "unit": "cases",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "High",
                    "reason": "Unknown but row-like.",
                },
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nSalad,40"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nSalad,Tomatoes,0.1,boxes"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert [row["ingredient"] for row in result["purchase_plan"]] == ["Tomatoes", "Fake Vendor Item"]
    assert result["purchase_plan"][1]["status"] == "Needs Review"


def test_claude_only_unknown_row_like_rows_do_not_fallback(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=2,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {
            "purchase_plan": [
                {
                    "ingredient": "Manager Special Sauce",
                    "suggested_purchase": 1,
                    "unit": "case",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "High",
                    "reason": "Claude returned a row-like recommendation.",
                }
            ]
        },
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nSalad,40"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nSalad,Tomatoes,0.1,boxes"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient"] == "Manager Special Sauce"
    assert result["purchase_plan"][0]["status"] == "Needs Review"


def test_claude_empty_rows_fall_back_with_no_valid_purchase_rows(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=2,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", lambda evidence_packet: {"purchase_plan": [{}]})

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nSalad,40"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nSalad,Tomatoes,0.1,boxes"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"] == "claude_validation_failed:no_valid_purchase_rows"


def test_claude_missing_plan_key_uses_repair_retry(monkeypatch) -> None:
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
    initial_payload = {"summary": {"forecast_mode": "claude_recipe_only"}, "manager_output": {"foo": "bar"}}
    calls: list[object] = []

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", lambda evidence_packet: initial_payload)

    def mock_reformat(raw_response: object) -> dict:
        calls.append(raw_response)
        return {"purchase_plan": [_claude_chicken_row()], "learning_notes": [], "review_warnings": []}

    monkeypatch.setattr(restock_planner_service, "reformat_restock_plan_with_claude", mock_reformat)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert calls == [initial_payload]
    assert result["summary"]["planner_source"] == "claude"
    assert result["purchase_plan"][0]["ingredient"] == "Chicken Breast"


def test_claude_missing_plan_key_and_repair_failure_falls_back(monkeypatch) -> None:
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

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {"summary": {"forecast_mode": "claude_recipe_only"}, "manager_output": {"foo": "bar"}},
    )
    monkeypatch.setattr(restock_planner_service, "reformat_restock_plan_with_claude", lambda raw_response: {"still_bad": []})

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"] == "claude_validation_failed:repair_retry_no_candidate_plan_list"


def test_claude_failure_falls_back_to_deterministic_plan(monkeypatch) -> None:
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

    def mock_generate(evidence_packet: dict) -> dict:
        raise TimeoutError("mock Claude timeout")

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"].startswith("claude_call_failed:TimeoutError:mock Claude timeout")
    assert result["purchase_plan"][0]["suggested_purchase"] == 17.5


def test_malformed_claude_payload_falls_back(monkeypatch) -> None:
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

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", lambda evidence_packet: {"purchase_plan": "bad"})
    monkeypatch.setattr(restock_planner_service, "reformat_restock_plan_with_claude", lambda raw_response: {"purchase_plan": "bad"})

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"] == "claude_validation_failed:purchase_plan_unrecoverable_type_string"


def test_unrecoverable_claude_purchase_plan_object_falls_back_with_specific_reason(monkeypatch) -> None:
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

    monkeypatch.setattr(
        restock_planner_service,
        "generate_restock_plan_with_claude",
        lambda evidence_packet: {"purchase_plan": {"unexpected": [_claude_chicken_row()]}},
    )
    monkeypatch.setattr(
        restock_planner_service,
        "reformat_restock_plan_with_claude",
        lambda raw_response: {"purchase_plan": {"unexpected": [_claude_chicken_row()]}},
    )

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"] == "claude_validation_failed:purchase_plan_unrecoverable_type_object"


def test_malformed_claude_json_falls_back_with_specific_reason(monkeypatch) -> None:
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

    def mock_generate(evidence_packet: dict) -> dict:
        raise ValueError("Claude response did not contain JSON")

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "deterministic_fallback"
    assert result["summary"]["fallback_reason"].startswith("claude_json_parse_failed")


def test_claude_unknown_ingredient_is_kept_and_negative_purchase_is_repaired(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Tomatoes",
                normalized_item_name="tomatoes",
                quantity=2,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    def mock_generate(evidence_packet: dict) -> dict:
        return {
            "summary": {"forecast_mode": "claude_recipe_only"},
            "purchase_plan": [
                {
                    "ingredient": "Tomatoes",
                    "suggested_purchase": -4,
                    "unit": "boxes",
                    "action": "hold",
                    "status": "Ready",
                    "confidence": "Medium",
                    "projected_need": 1,
                    "adjusted_need": 1,
                    "current_stock": 2,
                    "usage_signal": "medium",
                    "history_signal": "limited_history",
                    "risk_signal": "balanced",
                    "reason": "Current stock can cover projected demand.",
                },
                {
                    "ingredient": "Fake Vendor Item",
                    "suggested_purchase": 10,
                    "unit": "cases",
                    "action": "buy",
                    "status": "Ready",
                    "confidence": "High",
                    "projected_need": 10,
                    "adjusted_need": 10,
                    "current_stock": 0,
                    "usage_signal": "high",
                    "history_signal": "unknown",
                    "risk_signal": "stockout_risk",
                    "reason": "This should be dropped.",
                },
            ],
            "learning_notes": [],
            "review_warnings": [],
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nSalad,40"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nSalad,Tomatoes,0.1,boxes"),
        use_claude=True,
    )

    assert result["summary"]["planner_source"] == "claude"
    assert len(result["purchase_plan"]) == 2
    rows = {row["ingredient"]: row for row in result["purchase_plan"]}
    assert rows["Tomatoes"]["suggested_purchase"] == 0
    assert rows["Fake Vendor Item"]["suggested_purchase"] is None
    assert rows["Fake Vendor Item"]["status"] == "Needs Review"
    assert any("could not confidently match" in warning["warning"] for warning in result["review_warnings"])


def test_claude_stock_unknown_forces_low_confidence(monkeypatch) -> None:
    count = _count_with_entries([])

    def mock_generate(evidence_packet: dict) -> dict:
        return {
            "summary": {"forecast_mode": "claude_recipe_only"},
            "purchase_plan": [
                {
                    "ingredient": "Whole Milk",
                    "suggested_purchase": 3,
                    "unit": "gallons",
                    "action": "review",
                    "status": "Stock Unknown",
                    "confidence": "High",
                    "projected_need": 2.5,
                    "adjusted_need": 2.5,
                    "current_stock": None,
                    "usage_signal": "unknown",
                    "history_signal": "limited_history",
                    "risk_signal": "needs_review",
                    "reason": "No matching current stock row was found.",
                }
            ],
            "learning_notes": [],
            "review_warnings": [],
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nLatte,200"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nLatte,Whole Milk,0.05,gallons"),
        use_claude=True,
    )

    row = result["purchase_plan"][0]
    assert row["status"] == "Stock Unknown"
    assert row["confidence"] == "Low"


def test_claude_unit_mismatch_removes_unsafe_purchase_quantity(monkeypatch) -> None:
    count = _count_with_entries(
        [
            CountEntry(
                item_name="Chicken Breast",
                normalized_item_name="chicken breast",
                quantity=3,
                unit="boxes",
                status="Clean",
            )
        ]
    )

    def mock_generate(evidence_packet: dict) -> dict:
        return {
            "summary": {"forecast_mode": "claude_recipe_only"},
            "purchase_plan": [
                {
                    "ingredient": "Chicken Breast",
                    "suggested_purchase": 18,
                    "unit": "pounds",
                    "action": "buy",
                    "status": "Unit Mismatch",
                    "confidence": "Medium",
                    "projected_need": 25,
                    "adjusted_need": 25,
                    "current_stock": 3,
                    "usage_signal": "unknown",
                    "history_signal": "limited_history",
                    "risk_signal": "needs_review",
                    "reason": "Recipe uses pounds but current count is boxes, so manager review is required.",
                }
            ],
            "learning_notes": [],
            "review_warnings": [],
        }

    monkeypatch.setattr(restock_planner_service, "generate_restock_plan_with_claude", mock_generate)

    result = build_restock_plan(
        count,
        _csv("item_name,quantity_sold\nChicken Sandwich,400"),
        _csv("menu_item,ingredient_name,quantity_per_item,unit\nChicken Sandwich,Chicken Breast,0.25,pounds"),
        use_claude=True,
    )

    row = result["purchase_plan"][0]
    assert row["status"] == "Unit Mismatch"
    assert row["action"] == "review"
    assert row["confidence"] == "Low"
    assert row["suggested_purchase"] is None
    assert any("removed the purchase quantity" in warning["warning"] for warning in result["review_warnings"])


def test_missing_sales_columns_returns_clear_error() -> None:
    with pytest.raises(RestockPlannerError, match="Koe could not read sales quantities from this file"):
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
