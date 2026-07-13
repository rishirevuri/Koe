from app.services import external_ai_service
from app.services.external_ai_service import SYSTEM_PROMPT, normalize_claude_inventory_payload, parse_inventory_json_with_claude


def test_claude_prompt_requires_manager_ready_json_shape() -> None:
    assert "You are Koe, an expert restaurant inventory data-cleaning engine." in SYSTEM_PROMPT
    assert "parse the full transcript globally" in SYSTEM_PROMPT
    assert '"item_name_raw"' in SYSTEM_PROMPT
    assert '"item_name_clean"' in SYSTEM_PROMPT
    assert '"category"' in SYSTEM_PROMPT
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
            "category": "Other",
            "quantity": None,
            "unit": None,
            "status": "Needs Review",
            "original_phrase": "a few tomatoes",
        }
    ]
    assert parsed["summary"]["rows_needing_review"] == 1
    assert parsed["summary"]["manager_insights"] == ["1 row needs manager review before export."]


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
    assert by_name["Coke cans"]["quantity"] == 18
    assert by_name["Limes"]["quantity"] is None
    assert by_name["Limes"]["status"] == "Needs Review"
    assert by_name["Ice cream"]["quantity"] == 2.25
    assert by_name["Ice cream"]["category"] == "Frozen"

    bad_names = {"of", "packs of", "cases of"}
    assert not any(item["item_name_clean"].lower() in bad_names for item in parsed["items"])
    assert not any("actually change that to" in item["item_name_clean"].lower() for item in parsed["items"])
