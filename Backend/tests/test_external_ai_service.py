from app.services.external_ai_service import SYSTEM_PROMPT, normalize_claude_inventory_payload


def test_claude_prompt_requires_manager_ready_json_shape() -> None:
    assert "You are Koe, an AI inventory assistant for restaurants." in SYSTEM_PROMPT
    assert '"item_name_raw"' in SYSTEM_PROMPT
    assert '"item_name_clean"' in SYSTEM_PROMPT
    assert '"items"' in SYSTEM_PROMPT
    assert '"summary"' in SYSTEM_PROMPT
    assert "Return only valid JSON" in SYSTEM_PROMPT
    assert "Do not invent items" in SYSTEM_PROMPT
    assert '"manager_note":' not in SYSTEM_PROMPT


def test_normalize_claude_inventory_payload_items_shape() -> None:
    payload = {
        "items": [
            {
                "item_name_raw": "olive oil",
                "item_name_clean": "Olive oil",
                "quantity": 2.5,
                "unit": "bottles",
                "status": "Partial Quantity",
                "original_phrase": "3 bottles of olive oil, one is half empty",
            },
            {
                "item_name_raw": "eggs",
                "item_name_clean": "Eggs",
                "quantity": 120,
                "unit": "eggs",
                "status": "Converted Unit",
                "original_phrase": "10 dozen eggs",
            },
        ],
        "summary": {"manager_insights": ["Two items were parsed."]},
    }

    parsed = normalize_claude_inventory_payload(payload)

    assert parsed["items"] == payload["items"]
    assert parsed["summary"] == {
        "items_counted": 2,
        "rows_needing_review": 0,
        "partial_quantities": 1,
        "missing_units": 0,
        "converted_units": 1,
        "possible_duplicates": 0,
        "manager_insights": ["Two items were parsed."],
    }


def test_normalize_claude_inventory_payload_legacy_entries_shape() -> None:
    payload = {
        "entries": [
            {
                "raw_phrase": "a few tomatoes",
                "item_name": "Tomatoes",
                "quantity": None,
                "unit": None,
                "needs_review": True,
                "review_reason": "Quantity was vague; manager should confirm exact count.",
            }
        ]
    }

    parsed = normalize_claude_inventory_payload(payload)

    assert parsed["items"] == [
        {
            "item_name_raw": "Tomatoes",
            "item_name_clean": "Tomatoes",
            "quantity": None,
            "unit": None,
            "status": "Needs Review",
            "original_phrase": "a few tomatoes",
        }
    ]
    assert parsed["summary"]["rows_needing_review"] == 1
    assert parsed["summary"]["manager_insights"] == ["1 row needs manager review before export."]
