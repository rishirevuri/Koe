from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed


client = TestClient(app)


def setup_function() -> None:
    seed(reset=True)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Koe Backend"}


def test_seed_demo_data_available() -> None:
    response = client.get("/inventory/items", params={"restaurant_id": 1})
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"Olive oil", "Lettuce", "Tomatoes", "Cheese"}.issubset(names)


def test_voice_parse_save_report_and_csv() -> None:
    count_response = client.post("/counts", json={"restaurant_id": 1, "area": "Dry Storage", "notes": "Sunday night count"})
    assert count_response.status_code == 200
    count_id = count_response.json()["id"]

    text = (
        "We have 3 bottles of olive oil, one of which is half empty, "
        "3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese."
    )
    parse_response = client.post(
        "/ai/parse-voice",
        json={"restaurant_id": 1, "count_session_id": count_id, "text": text, "area": "Dry Storage", "save": True},
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
    count_id = client.post("/counts", json={"restaurant_id": 1, "area": "Walk-in"}).json()["id"]
    response = client.post(
        "/ai/parse-upload",
        json={"restaurant_id": 1, "count_session_id": count_id, "text": "Mystery sauce 4 boxes", "area": "Walk-in", "save": True},
    )
    assert response.status_code == 200
    issues = client.get("/issues", params={"restaurant_id": 1}).json()
    assert any(issue["issue_type"] == "unknown_item" for issue in issues)


def test_vague_partial_phrase_creates_review_flag() -> None:
    count_id = client.post("/counts", json={"restaurant_id": 1, "area": "Dry Storage"}).json()["id"]
    response = client.post(
        "/ai/parse-voice",
        json={
            "restaurant_id": 1,
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


def test_integrations_disabled_without_keys() -> None:
    response = client.post("/integrations/transcribe-audio", json={"filename": "count.m4a"})
    assert response.status_code == 200
    assert response.json()["configured"] is False
