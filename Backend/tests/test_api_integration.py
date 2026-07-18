import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app import auth as auth_deps
from app.config import Settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import CountEntry, CountSession, InventoryItem, Issue, Restaurant
from app.routes import ai, integrations
from app.routes import auth as auth_routes
from app.seed import seed
from app.services import external_ai_service, google_sheets_service, speech_to_text_service
from app.services.voice_parse_service import ParsedCandidate


client = TestClient(app)
TEST_USER = auth_deps.SupabaseUser(user_id="test-supabase-user", email="tester@example.com")
CSV_HEADER = [
    "Count ID",
    "Restaurant ID",
    "Area",
    "Category",
    "Item Name",
    "Raw Item Name",
    "Quantity",
    "Unit",
    "Needed Quantity",
    "Status",
    "Original Phrase",
    "Counted By",
    "Created At",
]


def override_current_user() -> auth_deps.SupabaseUser:
    return TEST_USER


def setup_function() -> None:
    seed(reset=True)
    app.dependency_overrides.clear()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = override_current_user
    db = SessionLocal()
    try:
        restaurant = db.query(Restaurant).filter(Restaurant.name == "Smoking Pig BBQ").one()
        restaurant.owner_user_id = TEST_USER.user_id
        db.add(restaurant)
        db.commit()
    finally:
        db.close()


class DisabledIntegrationSettings:
    environment = "test"
    database_url = "sqlite:///./data/koe.db"
    enable_external_ai = False
    speech_provider = "elevenlabs"
    text_ai_provider = "claude"
    payments_enabled = False

    supabase_url = None
    supabase_anon_key = None
    supabase_service_role_key = None
    elevenlabs_api_key = "test-elevenlabs-key"
    gemini_api_key = None
    google_api_key = None
    anthropic_api_key = "test-anthropic-key"
    anthropic_model = "claude-test-model"
    google_sheets_client_id = None
    google_sheets_client_secret = None
    google_sheets_redirect_uri = "http://localhost:8000/integrations/google/callback"

    @staticmethod
    def _has_real_value(value: str | None) -> bool:
        return bool(value and value.strip() and not value.strip().startswith("your_"))

    @property
    def is_supabase_configured(self) -> bool:
        return False

    @property
    def is_gemini_configured(self) -> bool:
        return False

    @property
    def is_elevenlabs_configured(self) -> bool:
        return True

    @property
    def is_claude_configured(self) -> bool:
        return True

    @property
    def is_google_sheets_configured(self) -> bool:
        return False


def use_disabled_integration_settings(monkeypatch) -> None:
    settings = DisabledIntegrationSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    monkeypatch.setattr(integrations, "get_settings", lambda: settings)
    monkeypatch.setattr(speech_to_text_service, "get_settings", lambda: settings)
    monkeypatch.setattr(external_ai_service, "get_settings", lambda: settings)
    monkeypatch.setattr(google_sheets_service, "get_settings", lambda: settings)


def count_entry_columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("count_entries")}


class EnabledClaudeSettings(DisabledIntegrationSettings):
    enable_external_ai = True


@pytest.fixture(autouse=True)
def isolate_external_integrations(monkeypatch) -> None:
    use_disabled_integration_settings(monkeypatch)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Koe Backend"}


def test_protected_route_without_token_returns_401() -> None:
    app.dependency_overrides.pop(auth_deps.get_current_supabase_user, None)
    response = client.get("/inventory/items")
    assert response.status_code == 401


def test_auth_me_without_token_returns_401() -> None:
    app.dependency_overrides.pop(auth_deps.get_current_supabase_user, None)
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_seed_tester_data_available() -> None:
    response = client.get("/inventory/items")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"Olive oil", "Lettuce", "Tomatoes", "Cheese"}.issubset(names)


def test_auth_me_returns_current_workspace() -> None:
    response = client.get("/auth/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == TEST_USER.user_id
    assert payload["email"] == TEST_USER.email
    assert payload["restaurant"]["name"] == "Smoking Pig BBQ"


def test_create_restaurant_is_idempotent_for_existing_owned_workspace() -> None:
    db = SessionLocal()
    try:
        existing_id = db.query(Restaurant).filter(Restaurant.name == "Smoking Pig BBQ").one().id
    finally:
        db.close()

    response = client.post("/restaurants", json={"name": "  Smoking Pig BBQ  "})

    assert response.status_code == 200
    assert response.json()["id"] == existing_id
    restaurants = client.get("/restaurants").json()
    assert [restaurant["name"] for restaurant in restaurants].count("Smoking Pig BBQ") == 1


def test_create_restaurant_claims_unowned_matching_workspace() -> None:
    db = SessionLocal()
    try:
        massimo = db.query(Restaurant).filter(Restaurant.name == "Massimo’s").one()
        massimo_id = massimo.id
        assert massimo.owner_user_id is None
    finally:
        db.close()

    response = client.post("/restaurants", json={"name": "Massimo’s"})

    assert response.status_code == 200
    assert response.json()["id"] == massimo_id
    restaurants = client.get("/restaurants").json()
    assert {restaurant["name"] for restaurant in restaurants} >= {"Smoking Pig BBQ", "Massimo’s"}


def test_create_restaurant_rejects_blank_name() -> None:
    response = client.post("/restaurants", json={"name": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Restaurant name is required"


def test_dev_link_route_disabled_outside_development(monkeypatch) -> None:
    settings = DisabledIntegrationSettings()
    settings.environment = "production"
    monkeypatch.setattr(auth_routes, "get_settings", lambda: settings)
    response = client.post(
        "/auth/dev-link-restaurant",
        json={"email": TEST_USER.email, "restaurant_name": "Massimo’s"},
    )
    assert response.status_code == 403


def test_voice_parse_save_report_and_csv() -> None:
    count_response = client.post("/counts", json={"area": "Dry Storage", "notes": "Sunday night count"})
    assert count_response.status_code == 200
    count_id = count_response.json()["id"]

    text = (
        "We have 3 bottles of olive oil, one of which is half empty, "
        "3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese."
    )
    parse_response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": text, "area": "Dry Storage", "save": True},
    )
    assert parse_response.status_code == 200
    entries = parse_response.json()["entries"]
    assert [(entry["item_name_clean"], entry["quantity"], entry["unit"]) for entry in entries] == [
        ("Olive oil", 2.5, "bottles"),
        ("Lettuce", 3.0, "heads"),
        ("Tomatoes", 5.0, "boxes"),
        ("Cheese", 2.0, "boxes"),
    ]
    assert all("needs_review" not in entry for entry in entries)
    assert all("manager_note" not in entry for entry in entries)
    assert entries[0]["status"] == "Partial Quantity"
    assert entries[0]["counted_by"] == TEST_USER.email
    assert entries[0]["par_status"] == "low"
    assert entries[0]["estimated_par_quantity"] == 3
    assert entries[0]["par_unit"] == "bottles"
    assert entries[0]["is_demo_estimate"] is True
    assert {entry["area"] for entry in entries} == {"Dry Storage"}
    payload = parse_response.json()
    assert payload["parser_source"] == "deterministic_fallback"
    assert payload["fallback_reason"] == "external_ai_disabled"
    assert payload["external_ai_enabled"] is False
    assert payload["text_ai_provider"] == "claude"
    assert payload["anthropic_model"] == "claude-test-model"
    assert payload["anthropic_key_present"] is True

    report_response = client.get(f"/reports/{count_id}")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["summary"] == {"total_items": 4, "items_needing_review": 0}
    assert [(entry["item_name_clean"], entry["quantity"], entry["unit"]) for entry in report["entries"]] == [
        ("Olive oil", 2.5, "bottles"),
        ("Lettuce", 3.0, "heads"),
        ("Tomatoes", 5.0, "boxes"),
        ("Cheese", 2.0, "boxes"),
    ]
    assert [(entry["item_name_clean"], entry["category"]) for entry in report["entries"]] == [
        ("Olive oil", "Oils & Liquids"),
        ("Lettuce", "Produce"),
        ("Tomatoes", "Produce"),
        ("Cheese", "Dairy & Eggs"),
    ]
    assert {entry["area"] for entry in report["entries"]} == {"Dry Storage"}

    csv_response = client.get(f"/reports/{count_id}/csv")
    assert csv_response.status_code == 200
    csv_text = csv_response.text
    csv_rows = list(csv.reader(io.StringIO(csv_text)))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][:12] == [
        str(count_id),
        "2",
        "Dry Storage",
        "Oils & Liquids",
        "Olive oil",
        "olive oil",
        "2.5",
        "bottles",
        "TBD",
        "Partial Quantity",
        "3 bottles of olive oil, one of which is half empty",
        TEST_USER.email,
    ]
    assert ["Lettuce", "lettuce", "3.0", "heads", "TBD", "Clean"] in [row[4:10] for row in csv_rows[1:]]
    assert ["Tomatoes", "tomatoes", "5.0", "boxes", "TBD", "Clean"] in [row[4:10] for row in csv_rows[1:]]
    assert ["Cheese", "cheese", "2.0", "boxes", "TBD", "Clean"] in [row[4:10] for row in csv_rows[1:]]
    assert "Needs Review" not in csv_text
    assert "Manager Note" not in csv_text


def test_voice_parse_needed_quantity_saves_report_and_csv() -> None:
    count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "We have 2 boxes of tomatoes and need 6 more boxes.",
            "area": "Walk-in",
            "save": True,
        },
    )

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["item_name_clean"] == "Tomatoes"
    assert entry["quantity"] == 2
    assert entry["unit"] == "boxes"
    assert entry["needed_quantity"] == "6 boxes"

    report = client.get(f"/reports/{count_id}").json()
    assert report["entries"][0]["quantity"] == 2
    assert report["entries"][0]["needed_quantity"] == "6 boxes"

    csv_rows = list(csv.DictReader(io.StringIO(client.get(f"/reports/{count_id}/csv").text)))
    assert list(csv_rows[0].keys()) == CSV_HEADER
    assert csv_rows[0]["Quantity"] == "2.0"
    assert csv_rows[0]["Unit"] == "boxes"
    assert csv_rows[0]["Needed Quantity"] == "6 boxes"


def test_voice_parse_repairs_legacy_count_entry_category_column() -> None:
    with engine.begin() as connection:
        if "category" in count_entry_columns():
            connection.execute(text("ALTER TABLE count_entries DROP COLUMN category"))
    assert "category" not in count_entry_columns()

    count_response = client.post("/counts", json={"area": "Dry Storage"})
    assert count_response.status_code == 200
    count_id = count_response.json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "10 lemons, 8 cans of tomato sauce, 198 eggs, and 0.5 cases of napkins.",
            "area": "Dry Storage",
            "save": True,
        },
    )

    assert response.status_code == 200
    assert "category" in count_entry_columns()
    payload = response.json()
    assert payload["saved"] is True
    assert payload["entries"]
    assert all(entry["is_demo_estimate"] is True for entry in payload["entries"])


def test_voice_parse_repairs_legacy_count_entry_needed_quantity_column() -> None:
    with engine.begin() as connection:
        if "needed_quantity" in count_entry_columns():
            connection.execute(text("ALTER TABLE count_entries DROP COLUMN needed_quantity"))
    assert "needed_quantity" not in count_entry_columns()

    count_response = client.post("/counts", json={"area": "Dry Storage"})
    assert count_response.status_code == 200
    count_id = count_response.json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "3 bottles of olive oil.",
            "area": "Dry Storage",
            "save": True,
        },
    )

    assert response.status_code == 200
    assert "needed_quantity" in count_entry_columns()
    assert response.json()["entries"][0]["needed_quantity"] == "TBD"


def test_count_entry_model_accepts_category_constructor_keyword() -> None:
    assert "category" in inspect(CountEntry).attrs.keys()
    assert "needed_quantity" in inspect(CountEntry).attrs.keys()

    entry = CountEntry(category="Produce", needed_quantity="6 boxes")

    assert entry.category == "Produce"
    assert entry.needed_quantity == "6 boxes"


def test_voice_parse_saves_claude_category(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        return [
            ParsedCandidate(
                raw_phrase="16 tomatoes",
                quantity=16,
                unit="individual",
                item_name="Tomatoes",
                partial_detail=None,
                needs_review=False,
                review_reason=None,
                status="Clean",
                category="Produce",
                needed_quantity="6 boxes",
            )
        ]

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "16 tomatoes",
            "area": "Walk-in",
            "save": True,
        },
    )

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["item_name_clean"] == "Tomatoes"
    assert entry["quantity"] == 16
    assert entry["unit"] == "individual"
    assert entry["category"] == "Produce"
    assert entry["needed_quantity"] == "6 boxes"

    db = SessionLocal()
    try:
        saved_entry = db.query(CountEntry).filter(CountEntry.count_session_id == count_id).one()
        assert saved_entry.category == "Produce"
        assert saved_entry.needed_quantity == "6 boxes"
    finally:
        db.close()

    report = client.get(f"/reports/{count_id}").json()
    assert report["entries"][0]["needed_quantity"] == "6 boxes"

    csv_rows = list(csv.DictReader(io.StringIO(client.get(f"/reports/{count_id}/csv").text)))
    assert csv_rows[0]["Quantity"] == "16.0"
    assert csv_rows[0]["Unit"] == "individual"
    assert csv_rows[0]["Needed Quantity"] == "6 boxes"


def test_voice_parse_vague_claude_quantity_exports_blank(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        return [
            ParsedCandidate(
                raw_phrase="a few takeout containers, but I do not know the exact count",
                quantity=None,
                unit=None,
                item_name="Takeout containers",
                partial_detail=None,
                needs_review=True,
                review_reason="a few takeout containers, but I do not know the exact count",
                status="Needs Review",
                category="Supplies",
            )
        ]

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Storage"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "a few takeout containers, but I do not know the exact count",
            "area": "Storage",
            "save": True,
        },
    )

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["quantity"] is None
    assert entry["unit"] is None
    assert entry["status"] == "Needs Review"
    assert entry["category"] == "Supplies"

    report = client.get(f"/reports/{count_id}").json()
    assert report["entries"][0]["quantity"] is None

    csv_rows = list(csv.reader(io.StringIO(client.get(f"/reports/{count_id}/csv").text)))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][:12] == [
        str(count_id),
        "2",
        "Storage",
        "Supplies",
        "Takeout containers",
        "Takeout containers",
        "",
        "",
        "TBD",
        "Needs Review",
        "a few takeout containers, but I do not know the exact count",
        TEST_USER.email,
    ]


def test_voice_parse_corrects_restaurant_categories_in_report_and_csv(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    rows = [
        ("Marinara sauce", "Dry Goods", 2, "jars", "Sauces & Condiments"),
        ("Pesto", "Dry Goods", 4, "containers", "Sauces & Condiments"),
        ("Tomato sauce", "Dry Goods", 8, "cans", "Sauces & Condiments"),
        ("Olive oil", "Dry Goods", 3, "bottles", "Oils & Liquids"),
        ("Canola oil", "Dry Goods", 5, "gallons", "Oils & Liquids"),
        ("Water bottles", "Liquids", 48, "bottles", "Beverages"),
        ("Burger buns", "Dry Goods", 48, "buns", "Bakery"),
        ("Bacon", "Meats", 2, "boxes", "Proteins"),
        ("Salmon", "Meats", 6, "pounds", "Proteins"),
        ("Chicken breast", "Meats", 4, "pounds", "Proteins"),
        ("Napkins", "Dry Goods", 1, "cases", "Supplies"),
        ("Paper cups", "Dry Goods", 500, "cups", "Supplies"),
    ]

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        return [
            ParsedCandidate(
                raw_phrase=f"{quantity} {unit} {name}",
                quantity=quantity,
                unit=unit,
                item_name=name,
                partial_detail=None,
                needs_review=False,
                review_reason=None,
                status="Clean",
                category=source_category,
            )
            for name, source_category, quantity, unit, _expected_category in rows
        ]

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": "category fixture", "area": "Dry Storage", "save": True},
    )

    assert response.status_code == 200
    response_categories = {entry["item_name_clean"]: entry["category"] for entry in response.json()["entries"]}
    assert response_categories == {name: expected for name, *_rest, expected in rows}

    report = client.get(f"/reports/{count_id}").json()
    report_categories = {entry["item_name_clean"]: entry["category"] for entry in report["entries"]}
    assert report_categories == response_categories

    csv_rows = list(csv.DictReader(io.StringIO(client.get(f"/reports/{count_id}/csv").text)))
    csv_categories = {row["Item Name"]: row["Category"] for row in csv_rows}
    assert csv_categories == response_categories


def test_unknown_item_creates_issue() -> None:
    count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]
    response = client.post(
        "/ai/parse-upload",
        json={"count_session_id": count_id, "text": "Mystery sauce 4 boxes", "area": "Walk-in", "save": True},
    )
    assert response.status_code == 200
    issues = client.get("/issues").json()
    assert any(issue["issue_type"] == "unknown_item" for issue in issues)


def test_vague_partial_phrase_creates_review_flag() -> None:
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "We have 5 bottles of olive oil, one almost empty.",
            "area": "Dry Storage",
            "save": True,
        },
    )
    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["status"] == "Needs Review"
    assert "needs_review" not in entry
    assert "review_reason" not in entry


def test_voice_parse_mocked_claude_success_returns_claude_source(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        return [
            ParsedCandidate(
                raw_phrase="claude saw seven jars of duck fat",
                quantity=7,
                unit="jars",
                item_name="Duck fat",
                partial_detail=None,
                needs_review=False,
                review_reason=None,
                status="Clean",
            )
        ]

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": "three bottles olive oil", "area": "Walk-in", "save": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parser_source"] == "claude"
    assert payload["fallback_reason"] == ""
    assert payload["external_ai_enabled"] is True
    assert payload["text_ai_provider"] == "claude"
    assert payload["anthropic_model"] == "claude-test-model"
    assert payload["anthropic_key_present"] is True
    assert [(entry["item_name_clean"], entry["quantity"], entry["unit"]) for entry in payload["entries"]] == [
        ("Duck fat", 7.0, "jars")
    ]
    assert payload["entries"][0]["status"] == "Clean"


def test_voice_parse_mocked_claude_failure_returns_fallback_source(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        raise TimeoutError("mock Claude timeout")

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": "3 bottles olive oil", "area": "Dry Storage", "save": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parser_source"] == "deterministic_fallback"
    assert payload["fallback_reason"].startswith("claude_error:TimeoutError:mock Claude timeout")
    assert payload["external_ai_enabled"] is True
    assert payload["text_ai_provider"] == "claude"
    assert payload["anthropic_model"] == "claude-test-model"
    assert payload["anthropic_key_present"] is True
    assert [(entry["item_name_clean"], entry["quantity"], entry["unit"]) for entry in payload["entries"]] == [
        ("Olive oil", 3.0, "bottles")
    ]


def test_voice_parse_mocked_claude_complex_transcript_returns_clean_global_rows(monkeypatch) -> None:
    settings = EnabledClaudeSettings()
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    transcript = (
        "I am counting the walk-in inventory now. We have 18 regular tomatoes, but 5 of those tomatoes are spoiled "
        "and should not be counted as usable. There are also 14 Roma tomatoes, and 3 of those are bruised but still "
        "usable, so keep the full Roma tomato count. I see 6 heads of lettuce, but one head is brown and should be "
        "thrown out. There are 4 boxes of cucumbers and 2 bunches of cilantro. We also have 1 case of 24 lemons, "
        "but 8 lemons are soft and unusable. There are some limes in the back, but I do not know the exact count. "
        "For dairy, we have 8 gallons of whole milk, 2 gallons of 2 percent milk, and 1 half gallon of heavy cream. "
        "There are 10 dozen eggs, but 7 eggs are cracked, so do not include those. For proteins, we have 3 ten-pound "
        "boxes of chicken breast, 12 pounds of ground beef, and 2 boxes of bacon. One bacon box is already open but "
        "still full, so count both boxes. In dry storage, there are 5 bags of flour, 2 bags of rice at 25 pounds each, "
        "3 jars of marinara sauce, and 10 cans of tomato sauce. We have 4 bags of burger buns, each bag has 12 buns, "
        "but one bag is stale and should not be counted. Behind the bar, there are 2 cases of 24 water bottles, "
        "18 cans of Coke, and 3 bottles of olive oil. One olive oil bottle is half empty. There are 2 gallons of "
        "canola oil. In the freezer, there are 3 boxes of frozen fries, but one box is half empty. There are 4 tubs "
        "of ice cream, but one tub is only a quarter full. We also have 2 boxes of mozzarella sticks. For supplies, "
        "I see 1 case of napkins, half a box of straws, and 3 rolls of receipt paper."
    )

    expected_rows = [
        ("Tomatoes", 13, "individual", "Clean", "Produce"),
        ("Roma tomatoes", 14, "individual", "Clean", "Produce"),
        ("Lettuce", 5, "heads", "Clean", "Produce"),
        ("Cucumbers", 4, "boxes", "Clean", "Produce"),
        ("Cilantro", 2, "bunches", "Clean", "Produce"),
        ("Lemons", 16, "individual", "Converted Unit", "Produce"),
        ("Limes", None, None, "Needs Review", "Produce"),
        ("Whole milk", 8, "gallons", "Clean", "Dairy & Eggs"),
        ("2 percent milk", 2, "gallons", "Clean", "Dairy & Eggs"),
        ("Heavy cream", 0.5, "gallons", "Converted Unit", "Dairy & Eggs"),
        ("Eggs", 113, "eggs", "Converted Unit", "Dairy & Eggs"),
        ("Chicken breast", 30, "pounds", "Converted Unit", "Proteins"),
        ("Ground beef", 12, "pounds", "Clean", "Proteins"),
        ("Bacon", 2, "boxes", "Clean", "Proteins"),
        ("Flour", 5, "bags", "Clean", "Dry Goods"),
        ("Rice", 50, "pounds", "Converted Unit", "Dry Goods"),
        ("Marinara sauce", 3, "jars", "Clean", "Sauces & Condiments"),
        ("Tomato sauce", 10, "cans", "Clean", "Sauces & Condiments"),
        ("Burger buns", 36, "buns", "Converted Unit", "Bakery"),
        ("Water bottles", 48, "bottles", "Converted Unit", "Beverages"),
        ("Coke", 18, "cans", "Clean", "Beverages"),
        ("Olive oil", 2.5, "bottles", "Partial Quantity", "Oils & Liquids"),
        ("Canola oil", 2, "gallons", "Clean", "Oils & Liquids"),
        ("Frozen fries", 2.5, "boxes", "Partial Quantity", "Frozen"),
        ("Ice cream", 3.25, "tubs", "Partial Quantity", "Frozen"),
        ("Mozzarella sticks", 2, "boxes", "Clean", "Frozen"),
        ("Napkins", 1, "cases", "Clean", "Supplies"),
        ("Straws", 0.5, "boxes", "Partial Quantity", "Supplies"),
        ("Receipt paper", 3, "rolls", "Clean", "Supplies"),
    ]

    def mock_parse_inventory_with_claude(text: str) -> list[ParsedCandidate]:
        assert text == transcript
        return [
            ParsedCandidate(
                raw_phrase=name,
                quantity=quantity,
                unit=unit,
                item_name=name,
                partial_detail=name if status == "Partial Quantity" else None,
                needs_review=status == "Needs Review",
                review_reason=name if status == "Needs Review" else None,
                status=status,
                category=category,
            )
            for name, quantity, unit, status, category in expected_rows
        ]

    monkeypatch.setattr(ai, "parse_inventory_with_claude", mock_parse_inventory_with_claude)
    count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": transcript, "area": "Walk-in", "save": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parser_source"] == "claude"
    assert payload["fallback_reason"] == ""
    actual_rows = [
        (entry["item_name_clean"], entry["quantity"], entry["unit"], entry["status"], entry["category"])
        for entry in payload["entries"]
    ]
    assert actual_rows == [
        (name, None if quantity is None else float(quantity), unit, status, category)
        for name, quantity, unit, status, category in expected_rows
    ]
    bad_fragments = {"regular tomatoes, but", "of those tomatoes are spoiled and should not be counted", "lemons but", "dozen eggs, but"}
    assert not any(entry["item_name_clean"].lower() in bad_fragments for entry in payload["entries"])


def test_parse_voice_area_updates_entries_report_and_csv_when_count_started_without_area() -> None:
    count_id = client.post("/counts", json={"notes": "No area at start"}).json()["id"]

    response = client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": "3 bottles olive oil", "area": "Walk-in", "save": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entries"][0]["area"] == "Walk-in"

    report = client.get(f"/reports/{count_id}").json()
    assert report["entries"][0]["area"] == "Walk-in"

    csv_text = client.get(f"/reports/{count_id}/csv").text
    csv_rows = list(csv.reader(io.StringIO(csv_text)))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][2] == "Walk-in"
    assert csv_rows[1][4:6] == ["Olive oil", "olive oil"]


def test_saved_counts_persist_for_same_user_and_are_account_scoped() -> None:
    first_count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    first_parse = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": first_count_id,
            "text": "3 bottles of olive oil",
            "area": "Dry Storage",
            "save": True,
        },
    )
    assert first_parse.status_code == 200
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    db = SessionLocal()
    try:
        first_count = db.get(CountSession, first_count_id)
        first_count.started_at = two_days_ago - timedelta(minutes=5)
        first_count.completed_at = two_days_ago
        db.add(first_count)
        db.commit()
    finally:
        db.close()

    second_count_id = client.post("/counts", json={"area": "Walk-in"}).json()["id"]
    second_parse = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": second_count_id,
            "text": "5 heads of lettuce",
            "area": "Walk-in",
            "save": True,
        },
    )
    assert second_parse.status_code == 200
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    db = SessionLocal()
    try:
        second_count = db.get(CountSession, second_count_id)
        second_count.started_at = yesterday - timedelta(minutes=5)
        second_count.completed_at = yesterday
        db.add(second_count)
        db.commit()
    finally:
        db.close()

    draft_count_id = client.post("/counts", json={"area": "Prep Station"}).json()["id"]

    # Simulate logout/re-auth by resetting dependency overrides without
    # touching database state, then authenticate as the same account again.
    app.dependency_overrides.clear()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = override_current_user

    counts_response = client.get("/counts")
    assert counts_response.status_code == 200
    counts = counts_response.json()
    assert [count["id"] for count in counts[:3]] == [second_count_id, first_count_id, draft_count_id]
    assert {first_count_id, second_count_id}.issubset({count["id"] for count in counts})
    completed = [count for count in counts if count["id"] in {first_count_id, second_count_id}]
    assert all(count["status"] == "completed" for count in completed)
    assert all(count["completed_at"] for count in completed)
    assert all(count["restaurant_id"] == 2 for count in completed)
    assert {count["id"]: count["summary"]["total_entries"] for count in completed} == {
        first_count_id: 1,
        second_count_id: 1,
    }

    report_response = client.get(f"/reports/{first_count_id}")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["count_id"] == first_count_id
    assert [(entry["item_name_clean"], entry["category"]) for entry in report["entries"]] == [
        ("Olive oil", "Oils & Liquids")
    ]

    csv_response = client.get(f"/reports/{first_count_id}/csv")
    assert csv_response.status_code == 200
    assert "Olive oil" in csv_response.text

    dashboard_response = client.get("/dashboard/summary")
    assert dashboard_response.status_code == 200
    counts_after_dashboard = client.get("/counts")
    assert counts_after_dashboard.status_code == 200
    assert {first_count_id, second_count_id, draft_count_id}.issubset({count["id"] for count in counts_after_dashboard.json()})

    other_user = auth_deps.SupabaseUser(user_id="other-persist-user", email="other@example.com")
    db = SessionLocal()
    try:
        other_restaurant = Restaurant(name="Other Owner", owner_user_id=other_user.user_id)
        db.add(other_restaurant)
        db.commit()
    finally:
        db.close()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = lambda: other_user

    other_counts = client.get("/counts")
    assert other_counts.status_code == 200
    assert first_count_id not in {count["id"] for count in other_counts.json()}
    assert client.get(f"/reports/{first_count_id}").status_code == 404
    assert client.get(f"/reports/{first_count_id}/csv").status_code == 404

    app.dependency_overrides.clear()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = override_current_user


def test_parse_voice_reused_completed_session_id_creates_separate_count() -> None:
    first_count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    first_parse = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": first_count_id,
            "text": "3 bottles of olive oil",
            "area": "Dry Storage",
            "save": True,
        },
    )
    assert first_parse.status_code == 200
    assert first_parse.json()["count_session_id"] == first_count_id

    second_parse = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": first_count_id,
            "text": "5 heads of lettuce",
            "area": "Walk-in",
            "save": True,
        },
    )

    assert second_parse.status_code == 200
    second_count_id = second_parse.json()["count_session_id"]
    assert second_count_id != first_count_id
    assert {entry["count_id"] for entry in second_parse.json()["entries"]} == {second_count_id}

    counts_response = client.get("/counts")
    assert counts_response.status_code == 200
    count_summaries = {count["id"]: count["summary"]["total_entries"] for count in counts_response.json()}
    assert count_summaries[first_count_id] == 1
    assert count_summaries[second_count_id] == 1

    first_report = client.get(f"/reports/{first_count_id}").json()
    second_report = client.get(f"/reports/{second_count_id}").json()
    assert [entry["item_name_clean"] for entry in first_report["entries"]] == ["Olive oil"]
    assert [entry["item_name_clean"] for entry in second_report["entries"]] == ["Lettuce"]

    first_csv = client.get(f"/reports/{first_count_id}/csv").text
    second_csv = client.get(f"/reports/{second_count_id}/csv").text
    assert "Olive oil" in first_csv
    assert "Lettuce" not in first_csv
    assert "Lettuce" in second_csv
    assert "Olive oil" not in second_csv


def test_parse_voice_without_session_id_creates_saved_count_session() -> None:
    response = client.post(
        "/ai/parse-voice",
        json={"text": "5 heads of lettuce", "area": "Walk-in", "save": True},
    )

    assert response.status_code == 200
    payload = response.json()
    count_id = payload["count_session_id"]
    assert isinstance(count_id, int)
    assert {entry["count_id"] for entry in payload["entries"]} == {count_id}

    report = client.get(f"/reports/{count_id}").json()
    assert report["count_id"] == count_id
    assert [entry["item_name_clean"] for entry in report["entries"]] == ["Lettuce"]


def test_parse_voice_cannot_append_to_another_users_count_session() -> None:
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    other_user = auth_deps.SupabaseUser(user_id="other-append-user", email="other-append@example.com")
    db = SessionLocal()
    try:
        db.add(Restaurant(name="Other Append Owner", owner_user_id=other_user.user_id))
        db.commit()
    finally:
        db.close()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = lambda: other_user

    response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "5 heads of lettuce",
            "area": "Walk-in",
            "save": True,
        },
    )

    assert response.status_code == 404
    app.dependency_overrides[auth_deps.get_current_supabase_user] = override_current_user
    assert client.get(f"/reports/{count_id}").status_code == 200


def test_delete_count_session_removes_saved_report_rows_and_csv() -> None:
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    parse_response = client.post(
        "/ai/parse-voice",
        json={
            "count_session_id": count_id,
            "text": "some limes in the back, but I do not know the exact count",
            "area": "Dry Storage",
            "save": True,
        },
    )
    assert parse_response.status_code == 200
    assert client.get(f"/reports/{count_id}").status_code == 200

    delete_response = client.delete(f"/counts/{count_id}")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "id": count_id}
    assert count_id not in {count["id"] for count in client.get("/counts").json()}
    assert client.get(f"/reports/{count_id}").status_code == 404
    assert client.get(f"/reports/{count_id}/csv").status_code == 404

    db = SessionLocal()
    try:
        assert db.get(CountSession, count_id) is None
        assert db.query(CountEntry).filter(CountEntry.count_session_id == count_id).count() == 0
        assert db.query(Issue).filter(Issue.count_session_id == count_id).count() == 0
    finally:
        db.close()


def test_delete_count_session_is_account_scoped() -> None:
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    assert client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": "3 bottles of olive oil", "area": "Dry Storage", "save": True},
    ).status_code == 200

    other_user = auth_deps.SupabaseUser(user_id="other-delete-user", email="other-delete@example.com")
    db = SessionLocal()
    try:
        db.add(Restaurant(name="Other Delete Owner", owner_user_id=other_user.user_id))
        db.commit()
    finally:
        db.close()
    app.dependency_overrides[auth_deps.get_current_supabase_user] = lambda: other_user

    assert client.delete(f"/counts/{count_id}").status_code == 404

    app.dependency_overrides[auth_deps.get_current_supabase_user] = override_current_user
    assert client.get(f"/reports/{count_id}").status_code == 200


def test_ownership_checks_prevent_other_restaurant_count_and_report() -> None:
    db = SessionLocal()
    try:
        massimo = db.query(Restaurant).filter(Restaurant.name == "Massimo’s").one()
        massimo.owner_user_id = "other-user"
        count = CountSession(restaurant_id=massimo.id, area="Walk-in")
        db.add_all([massimo, count])
        db.commit()
        db.refresh(count)
        count_id = count.id
    finally:
        db.close()

    count_response = client.get(f"/counts/{count_id}")
    report_response = client.get(f"/reports/{count_id}")
    csv_response = client.get(f"/reports/{count_id}/csv")

    assert count_response.status_code == 404
    assert report_response.status_code == 404
    assert csv_response.status_code == 404


def test_backend_settings_default_without_env(monkeypatch) -> None:
    for key in (
        "ENABLE_EXTERNAL_AI",
        "ELEVENLABS_API_KEY",
        "ANTHROPIC_API_KEY",
        "SPEECH_PROVIDER",
        "TEXT_AI_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)
    assert settings.enable_external_ai is False
    assert settings.speech_provider == "elevenlabs"
    assert settings.text_ai_provider == "claude"


def test_integrations_disabled_without_external_calls(monkeypatch) -> None:
    use_disabled_integration_settings(monkeypatch)
    response = client.post("/integrations/transcribe-audio", json={"filename": "count.m4a"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["provider"] == "elevenlabs"
    assert "ELEVENLABS_API_KEY" in payload["message"]
    assert "ENABLE_EXTERNAL_AI=true" in payload["message"]


def test_integrations_status_is_robust_to_local_keys(monkeypatch) -> None:
    use_disabled_integration_settings(monkeypatch)
    response = client.get("/integrations/status")
    assert response.status_code == 200
    payload = response.json()
    for key in (
        "external_ai_enabled",
        "supabase_configured",
        "elevenlabs_configured",
        "gemini_configured",
        "claude_configured",
        "google_sheets_configured",
        "payments_enabled",
    ):
        assert key in payload
    assert payload["external_ai_enabled"] is False
    assert payload["payments_enabled"] is False


def test_claude_placeholder_disabled_without_external_calls(monkeypatch) -> None:
    use_disabled_integration_settings(monkeypatch)
    response = client.post("/integrations/parse-with-claude", json={"transcript": "3 bottles olive oil"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["provider"] == "claude"
    assert "ANTHROPIC_API_KEY" in payload["message"]
    assert "ENABLE_EXTERNAL_AI=true" in payload["message"]


def test_google_sheets_placeholder_disabled_without_external_calls(monkeypatch) -> None:
    use_disabled_integration_settings(monkeypatch)
    response = client.post("/integrations/export-google-sheets", json={"count_id": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["provider"] == "google_sheets"
    assert "Google Sheets OAuth credentials" in payload["message"]
    assert "ENABLE_EXTERNAL_AI=true" in payload["message"]


def test_dashboard_summary_empty_state() -> None:
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["low_stock_items"] == []
    assert data["last_count_summary"] is None
    assert data["count_over_count_changes"] == []
    assert data["data_quality_insights"] == []
    assert data["estimated_par_summary"] == {
        "critical_items": 0,
        "low_items": 0,
        "unknown_items": 0,
        "watchlist_items": 0,
        "is_demo_estimate": True,
    }
    assert data["estimated_reorder_watchlist"] == []
    assert data["export_status"] == {"count_id": None, "exported": False}


def test_dashboard_summary_normal_state() -> None:
    text = (
        "We have 3 bottles of olive oil, one of which is half empty, "
        "3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese."
    )
    count_id = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    assert client.post(
        "/ai/parse-voice",
        json={"count_session_id": count_id, "text": text, "area": "Dry Storage", "save": True},
    ).status_code == 200

    data = client.get("/dashboard/summary").json()

    low = data["low_stock_items"]
    assert {row["item_name"] for row in low} == {"Olive oil", "Lettuce", "Tomatoes", "Cheese"}
    assert low[0]["item_name"] == "Lettuce"  # biggest shortfall (10 - 3 = 7)
    olive = next(row for row in low if row["item_name"] == "Olive oil")
    assert olive["current_quantity"] == 2.5
    assert olive["par_level"] == 6
    assert olive["shortfall"] == 3.5
    assert olive["unit"] == "bottles"

    summary = data["last_count_summary"]
    assert summary["count_id"] == count_id
    assert summary["area"] == "Dry Storage"
    assert summary["total_items_counted"] == 4
    assert summary["needs_review_count"] == 0

    assert "Olive oil was counted as a partial quantity (2.5 bottles)." in data["data_quality_insights"]
    assert "Demo par estimates enabled; review before ordering." in data["data_quality_insights"]

    par_summary = data["estimated_par_summary"]
    assert par_summary["critical_items"] == 1
    assert par_summary["low_items"] == 1
    assert par_summary["unknown_items"] == 2
    assert par_summary["watchlist_items"] == 2
    assert par_summary["is_demo_estimate"] is True

    watchlist = data["estimated_reorder_watchlist"]
    assert [(row["item_name"], row["par_status"]) for row in watchlist] == [
        ("Lettuce", "critical"),
        ("Olive oil", "low"),
    ]
    lettuce = watchlist[0]
    assert lettuce["quantity"] == 3
    assert lettuce["unit"] == "heads"
    assert lettuce["estimated_par_quantity"] == 8
    assert lettuce["par_unit"] == "heads"
    assert "common restaurant usage patterns" in lettuce["par_reason"].lower()

    assert data["export_status"] == {"count_id": count_id, "exported": False}
    assert client.get(f"/reports/{count_id}/csv").status_code == 200
    assert client.get("/dashboard/summary").json()["export_status"]["exported"] is True


def test_dashboard_count_over_count_changes() -> None:
    first = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    client.post(
        "/ai/parse-voice",
        json={"count_session_id": first, "text": "3 bottles of olive oil and 3 heads of lettuce", "area": "Dry Storage", "save": True},
    )
    second = client.post("/counts", json={"area": "Dry Storage"}).json()["id"]
    client.post(
        "/ai/parse-voice",
        json={"count_session_id": second, "text": "6 bottles of olive oil and 5 heads of lettuce", "area": "Dry Storage", "save": True},
    )

    changes = client.get("/dashboard/summary").json()["count_over_count_changes"]
    by_name = {row["item_name"]: row for row in changes}
    assert by_name["Olive oil"]["previous_quantity"] == 3
    assert by_name["Olive oil"]["current_quantity"] == 6
    assert by_name["Olive oil"]["delta"] == 3
    assert by_name["Lettuce"]["delta"] == 2
    assert changes[0]["item_name"] == "Olive oil"  # abs delta 3 > 2


def test_dashboard_restaurant_isolation() -> None:
    db = SessionLocal()
    try:
        massimo = db.query(Restaurant).filter(Restaurant.name == "Massimo’s").one()
        massimo.owner_user_id = "other-user"
        count = CountSession(restaurant_id=massimo.id, area="Freezer")
        db.add_all([massimo, count])
        db.flush()
        item = db.query(InventoryItem).filter(InventoryItem.restaurant_id == massimo.id).first()
        db.add(
            CountEntry(
                count_session_id=count.id,
                inventory_item_id=item.id,
                item_name=item.name,
                normalized_item_name=item.normalized_name,
                quantity=1,
                unit=item.default_unit,
                area="Freezer",
            )
        )
        db.commit()
    finally:
        db.close()

    data = client.get("/dashboard/summary").json()
    # TEST_USER's restaurant (Smoking Pig BBQ) has no counts, so nothing from
    # Massimo's workspace should appear here.
    assert data["last_count_summary"] is None
    assert data["low_stock_items"] == []
    assert data["count_over_count_changes"] == []
    assert data["export_status"]["count_id"] is None
