from app.services.voice_parse_service import parse_voice_text


def test_voice_parse_seeded_demo_sentence() -> None:
    text = (
        "We have 3 bottles of olive oil, one of which is half empty, "
        "3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese."
    )
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("olive oil", 2.5, "bottles"),
        ("lettuce", 3, "heads"),
        ("tomatoes", 5, "boxes"),
        ("cheese", 2, "boxes"),
    ]
