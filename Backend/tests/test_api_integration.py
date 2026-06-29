import pytest
from fastapi.testclient import TestClient

from app import auth as auth_deps
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import CountSession, Restaurant
from app.routes import ai, integrations
from app.routes import auth as auth_routes
from app.seed import seed
from app.services import external_ai_service, google_sheets_service, speech_to_text_service


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
    assert [(entry["item_name"], entry["quantity"], entry["unit"]) for entry in entries] == [
        ("Olive oil", 2.5, "bottles"),
        ("Lettuce", 3.0, "heads"),
        ("Tomatoes", 5.0, "boxes"),
        ("Cheese", 2.0, "boxes"),
    ]

    report_response = client.get(f"/reports/{count_id}")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["summary"] == {"total_items": 4, "items_needing_review": 0}
    assert [(entry["name"], entry["quantity"], entry["unit"]) for entry in report["entries"]] == [
        ("Olive oil", 2.5, "bottles"),
        ("Lettuce", 3.0, "heads"),
        ("Tomatoes", 5.0, "boxes"),
        ("Cheese", 2.0, "boxes"),
    ]

    csv_response = client.get(f"/reports/{count_id}/csv")
    assert csv_response.status_code == 200
    csv_text = csv_response.text
    assert "Olive oil,2.5,bottles" in csv_text
    assert "Lettuce,3.0,heads" in csv_text
    assert "Tomatoes,5.0,boxes" in csv_text
    assert "Cheese,2.0,boxes" in csv_text


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
    assert entry["needs_review"] is True
    assert entry["review_reason"] == "Vague partial quantity: almost empty"


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
