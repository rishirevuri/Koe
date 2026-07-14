import pytest
from fastapi.testclient import TestClient

from app import auth as auth_deps
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import CountEntry, CountSession, InventoryItem, Restaurant
from app.routes import ai, integrations
from app.routes import auth as auth_routes
from app.seed import seed
from app.services import external_ai_service, google_sheets_service, speech_to_text_service
from app.services.voice_parse_service import ParsedCandidate


client = TestClient(app)
TEST_USER = auth_deps.SupabaseUser(user_id="test-supabase-user", email="tester@example.com")


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
    assert {entry["area"] for entry in entries} == {"Dry Storage"}
    payload = parse_response.json()
    assert payload["parser_source"] == "deterministic_fallback"
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
    assert {entry["area"] for entry in report["entries"]} == {"Dry Storage"}

    csv_response = client.get(f"/reports/{count_id}/csv")
    assert csv_response.status_code == 200
    csv_text = csv_response.text
    assert "Count ID,Restaurant ID,Area,Raw Item Name,Clean Item Name,Quantity,Unit,Status,Original Phrase,Created At,Counted By" in csv_text
    assert "olive oil,Olive oil,2.5,bottles,Partial Quantity" in csv_text
    assert ",Dry Storage,olive oil,Olive oil," in csv_text
    assert "lettuce,Lettuce,3.0,heads,Clean" in csv_text
    assert "tomatoes,Tomatoes,5.0,boxes,Clean" in csv_text
    assert "cheese,Cheese,2.0,boxes,Clean" in csv_text
    assert "Needs Review" not in csv_text
    assert "Manager Note" not in csv_text


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
    assert payload["external_ai_enabled"] is True
    assert payload["text_ai_provider"] == "claude"
    assert payload["anthropic_model"] == "claude-test-model"
    assert payload["anthropic_key_present"] is True
    assert [(entry["item_name_clean"], entry["quantity"], entry["unit"]) for entry in payload["entries"]] == [
        ("Olive oil", 3.0, "bottles")
    ]


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
    assert ",Walk-in,olive oil,Olive oil," in csv_text


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
