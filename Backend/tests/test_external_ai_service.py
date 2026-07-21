from app.services import external_ai_service
from app.services.external_ai_service import (
    SYSTEM_PROMPT,
    _coerce_candidate,
    normalize_claude_inventory_payload,
    parse_inventory_json_with_claude,
)


def test_claude_prompt_requires_manager_ready_json_shape() -> None:
    assert "You are Koe, an expert restaurant inventory data-cleaning engine." in SYSTEM_PROMPT
    assert "parse the full transcript globally" in SYSTEM_PROMPT
    assert '"item_name_raw"' in SYSTEM_PROMPT
    assert '"item_name_clean"' in SYSTEM_PROMPT
    assert '"category"' in SYSTEM_PROMPT
    assert '"needed_quantity"' in SYSTEM_PROMPT
    assert "Do not infer needed_quantity from par levels" in SYSTEM_PROMPT
    assert "Handle container fullness descriptions" in SYSTEM_PROMPT
    assert '"quantity": number | string | null' in SYSTEM_PROMPT
    assert '"items"' in SYSTEM_PROMPT
    assert '"summary"' in SYSTEM_PROMPT
    assert "No text outside JSON" in SYSTEM_PROMPT
    assert "Never create item names like" in SYSTEM_PROMPT
    assert '"manager_note":' not in SYSTEM_PROMPT


def test_normalize_claude_inventory_payload_items_shape() -> None:
    payload = {
        "items": [
            {
                "item_name_raw": "olive oil",
                "item_name_clean": "Olive oil",
                "category": "Liquids",
                "quantity": 2.5,
                "unit": "bottles",
                "needed_quantity": "6 bottles",
                "status": "Partial Quantity",
                "original_phrase": "3 bottles of olive oil, one is half empty",
            },
            {
                "item_name_raw": "eggs",
                "item_name_clean": "Eggs",
                "category": "Dairy & Eggs",
                "quantity": 120,
                "unit": "eggs",
                "status": "Converted Unit",
                "original_phrase": "10 dozen eggs",
            },
        ],
        "summary": {"manager_insights": ["Two items were parsed."]},
    }

    parsed = normalize_claude_inventory_payload(payload)

    assert parsed["items"] == [
        {
            **payload["items"][0],
            "category": "Oils & Liquids",
        },
        {**payload["items"][1], "needed_quantity": "TBD"},
    ]
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
            "category": "Produce",
            "quantity": None,
            "unit": None,
            "needed_quantity": "TBD",
            "status": "Needs Review",
            "original_phrase": "a few tomatoes",
        }
    ]
    assert parsed["summary"]["rows_needing_review"] == 1
    assert parsed["summary"]["manager_insights"] == ["1 row needs manager review before export."]


def test_coerce_candidate_cleans_obvious_units_and_vague_quantity() -> None:
    rows = [
        {"item_name_clean": "Paper cups", "quantity": 1000, "unit": "individual", "status": "Clean"},
        {"item_name_clean": "Veggie burger patties", "quantity": 30, "unit": "individual", "status": "Clean"},
        {"item_name_clean": "Hamburger buns", "quantity": 4, "unit": "individual", "status": "Clean"},
        {
            "item_name_clean": "Takeout containers",
            "quantity": None,
            "unit": None,
            "status": "Needs Review",
            "original_phrase": "a few takeout containers, not sure how many",
        },
    ]

    candidates = [_coerce_candidate(row) for row in rows]

    assert [(candidate.item_name, candidate.quantity, candidate.unit, candidate.status) for candidate in candidates] == [
        ("Paper cups", 1000.0, "cups", "Clean"),
        ("Veggie burger patties", 30.0, "patties", "Clean"),
        ("Hamburger buns", 4.0, "buns", "Clean"),
        ("Takeout containers", None, None, "Needs Review"),
    ]


def test_coerce_candidate_preserves_needed_quantity_without_overwriting_quantity() -> None:
    candidate = _coerce_candidate(
        {
            "item_name_clean": "Tomatoes",
            "quantity": 2,
            "unit": "boxes",
            "needed_quantity": "6 boxes",
            "status": "Clean",
            "original_phrase": "We have 2 boxes of tomatoes and need 6 more boxes.",
        }
    )

    assert candidate is not None
    assert candidate.item_name == "Tomatoes"
    assert candidate.quantity == 2
    assert candidate.unit == "boxes"
    assert candidate.needed_quantity == "6 boxes"


def test_coerce_candidate_preserves_qualitative_fullness_quantity() -> None:
    candidate = _coerce_candidate(
        {
            "item_name_clean": "Peanut butter",
            "quantity": "Decently filled",
            "unit": "bucket",
            "needed_quantity": "TBD",
            "original_phrase": "a bucket of peanut butter and it's pretty full",
        }
    )

    assert candidate is not None
    assert candidate.item_name == "Peanut butter"
    assert candidate.quantity is None
    assert candidate.quantity_label == "Decently filled"
    assert candidate.unit == "bucket"
    assert candidate.status == "Needs Review"
    assert candidate.needs_review is True


def test_coerce_candidate_maps_fullness_fraction_to_numeric_quantity() -> None:
    candidate = _coerce_candidate(
        {
            "item_name_clean": "Ranch",
            "quantity": "half full",
            "unit": "tub",
            "status": "Partial Quantity",
            "original_phrase": "one tub of ranch half full",
        }
    )

    assert candidate is not None
    assert candidate.quantity == 0.5
    assert candidate.quantity_label is None
    assert candidate.unit == "tub"


class EnabledClaudeSettings:
    enable_external_ai = True
    text_ai_provider = "claude"
    anthropic_api_key = "test-key"
    anthropic_model = "claude-test-model"
    environment = "test"
    debug_parse = True

    @property
    def is_claude_configured(self) -> bool:
        return True


class MockClaudeResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "content": [
                {
                    "type": "text",
                    "text": """
{
  "items": [
    {"item_name_raw":"tomatoes","item_name_clean":"Tomatoes","category":"Produce","quantity":12,"unit":"individual","status":"Clean","original_phrase":"10 tomatoes, actually make that 12 tomatoes"},
    {"item_name_raw":"Roma tomatoes","item_name_clean":"Roma tomatoes","category":"Produce","quantity":10,"unit":"individual","status":"Clean","original_phrase":"10 Roma tomatoes in the corner"},
    {"item_name_raw":"lettuce","item_name_clean":"Lettuce","category":"Produce","quantity":5,"unit":"heads","status":"Clean","original_phrase":"5 heads of lettuce"},
    {"item_name_raw":"cilantro","item_name_clean":"Cilantro","category":"Produce","quantity":4,"unit":"bunches","status":"Clean","original_phrase":"3 bunches, wait no scratch that, it is 4 bunches of cilantro"},
    {"item_name_raw":"whole milk","item_name_clean":"Whole milk","category":"Dairy & Eggs","quantity":10,"unit":"gallons","status":"Clean","original_phrase":"10 gallons of whole milk"},
    {"item_name_raw":"two percent milk","item_name_clean":"2 percent milk","category":"Dairy & Eggs","quantity":3,"unit":"gallons","status":"Clean","original_phrase":"3 gallons of two percent milk"},
    {"item_name_raw":"heavy cream","item_name_clean":"Heavy cream","category":"Dairy & Eggs","quantity":0.5,"unit":"gallons","status":"Partial Quantity","original_phrase":"half a gallon of heavy cream"},
    {"item_name_raw":"eggs","item_name_clean":"Eggs","category":"Dairy & Eggs","quantity":198,"unit":"eggs","status":"Converted Unit","original_phrase":"12 dozen eggs, but 6 eggs are cracked; also 2 trays of 30 eggs"},
    {"item_name_raw":"water bottles","item_name_clean":"Water bottles","category":"Liquids","quantity":48,"unit":"bottles","status":"Converted Unit","original_phrase":"2 cases of 24 water bottles"},
    {"item_name_raw":"Coke cans","item_name_clean":"Coke cans","category":"Bar","quantity":18,"unit":"cans","status":"Converted Unit","original_phrase":"3 packs of 6 Coke cans"},
    {"item_name_raw":"limes","item_name_clean":"Limes","category":"Bar","quantity":null,"unit":null,"status":"Needs Review","original_phrase":"a few limes but I do not know the exact count"},
    {"item_name_raw":"ice cream","item_name_clean":"Ice cream","category":"Frozen","quantity":2.25,"unit":"tubs","status":"Partial Quantity","original_phrase":"3 tubs of ice cream, but one tub is only a quarter full"}
  ],
  "summary": {
    "items_counted": 12,
    "rows_needing_review": 1,
    "partial_quantities": 2,
    "converted_units": 3,
    "missing_units": 0,
    "possible_duplicates": 0,
    "manager_insights": ["Hard transcript parsed into clean rows."]
  }
}
""",
                }
            ]
        }


def test_mocked_claude_hard_transcript_behavior(monkeypatch) -> None:
    transcript = (
        "Okay I am doing the inventory count now. I see 10 tomatoes, actually make that 12 tomatoes because "
        "there are 2 more on the bottom shelf. There are also 10 Roma tomatoes in the corner, those are separate "
        "from the regular tomatoes. I have 10 gallons of whole milk and 3 gallons of two percent milk. There is "
        "half a gallon of heavy cream. I see 12 dozen eggs, but 6 eggs are cracked so do not count those as usable. "
        "There are also 2 trays of 30 eggs. I have 2 cases of 24 water bottles, and 3 packs of 6 Coke cans. "
        "There are a few limes but I do not know the exact count. There are 3 tubs of ice cream, but one tub is only a quarter full."
    )
    captured: dict = {}

    def mock_post(url, headers, json, timeout):
        captured["content"] = json["messages"][0]["content"]
        return MockClaudeResponse()

    monkeypatch.setattr(external_ai_service, "get_settings", lambda: EnabledClaudeSettings())
    monkeypatch.setattr(external_ai_service.httpx, "post", mock_post)

    parsed = parse_inventory_json_with_claude(transcript)
    by_name = {item["item_name_clean"]: item for item in parsed["items"]}

    assert transcript in captured["content"]
    assert by_name["Tomatoes"]["quantity"] == 12
    assert by_name["Roma tomatoes"]["quantity"] == 10
    assert by_name["2 percent milk"]["quantity"] == 3
    assert by_name["Heavy cream"]["quantity"] == 0.5
    assert by_name["Eggs"]["quantity"] == 198
    assert by_name["Water bottles"]["quantity"] == 48
    assert by_name["Water bottles"]["category"] == "Beverages"
    assert by_name["Coke cans"]["quantity"] == 18
    assert by_name["Coke cans"]["category"] == "Beverages"
    assert by_name["Limes"]["quantity"] is None
    assert by_name["Limes"]["category"] == "Produce"
    assert by_name["Limes"]["status"] == "Needs Review"
    assert by_name["Ice cream"]["quantity"] == 2.25
    assert by_name["Ice cream"]["category"] == "Frozen"

    bad_names = {"of", "packs of", "cases of"}
    assert not any(item["item_name_clean"].lower() in bad_names for item in parsed["items"])
    assert not any("actually change that to" in item["item_name_clean"].lower() for item in parsed["items"])
