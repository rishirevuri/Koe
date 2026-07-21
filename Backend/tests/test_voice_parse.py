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


def test_voice_parse_browser_transcript_with_number_words_and_no_punctuation() -> None:
    text = (
        "we have three bottles of olive oil one of which is half empty "
        "three heads of lettuce five boxes of tomatoes and two boxes of cheese"
    )
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("olive oil", 2.5, "bottles"),
        ("lettuce", 3, "heads"),
        ("tomatoes", 5, "boxes"),
        ("cheese", 2, "boxes"),
    ]


def test_voice_parse_partial_variant_one_of_them() -> None:
    text = "we have 3 bottles of olive oil one of them is half empty 3 heads of lettuce"
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("olive oil", 2.5, "bottles"),
        ("lettuce", 3, "heads"),
    ]


def test_voice_parse_no_unit_defaults_to_individual() -> None:
    parsed = parse_voice_text("i have 10 cucumbers")
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("cucumbers", 10, "individual"),
    ]


def test_voice_parse_no_unit_then_unit_phrase_stays_separate() -> None:
    text = "i have 10 tomatoes and i also have 10 cartons of eggs"
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("tomatoes", 10, "individual"),
        ("eggs", 10, "cartons"),
    ]


def test_voice_parse_speech_connector_does_not_attach_to_item() -> None:
    text = "i have 10 tomatoes and then i said i also have 10 cartridges of eggs"
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("tomatoes", 10, "individual"),
        ("eggs", 10, "cartridges"),
    ]


def test_voice_parse_dangling_connector_does_not_attach_to_item() -> None:
    text = "i have 10 eggs and then i have 30 mg of salt"
    parsed = parse_voice_text(text)
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("eggs", 10, "individual"),
        ("salt", 30, "milligrams"),
    ]


def test_voice_parse_metric_units_are_units() -> None:
    parsed = parse_voice_text("i have 20 grams of salt")
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("salt", 20, "grams"),
    ]


def test_voice_parse_pack_and_bunch_units_are_not_item_fragments() -> None:
    parsed = parse_voice_text("i have 3 packs of buns and 4 bunches cilantro")
    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("buns", 3, "packs"),
        ("cilantro", 4, "bunches"),
    ]


def test_voice_parse_vague_quantity_stays_unknown() -> None:
    parsed = parse_voice_text("a few takeout containers, not sure how many")

    assert len(parsed) == 1
    row = parsed[0]
    assert row.item_name == "takeout containers"
    assert row.quantity is None
    assert row.unit is None
    assert row.status == "Needs Review"
    assert row.needs_review is True
    assert row.raw_phrase == "a few takeout containers"


def test_voice_parse_obvious_item_units() -> None:
    parsed = parse_voice_text("1000 paper cups, 30 veggie burger patties, and 4 hamburger buns")

    assert [(item.item_name, item.quantity, item.unit) for item in parsed] == [
        ("paper cups", 1000, "cups"),
        ("veggie burger patties", 30, "patties"),
        ("hamburger buns", 4, "buns"),
    ]


def test_voice_parse_simple_needed_quantity_stays_separate() -> None:
    parsed = parse_voice_text("We have 2 boxes of tomatoes and need 6 more boxes. We have 10 lemons and need 30 more.")

    assert [(item.item_name, item.quantity, item.unit, item.needed_quantity) for item in parsed] == [
        ("tomatoes", 2, "boxes", "6 boxes"),
        ("lemons", 10, "individual", "30 individual"),
    ]


def test_voice_parse_container_fullness_keeps_qualitative_quantity() -> None:
    parsed = parse_voice_text("We have a bucket of peanut butter and it's pretty full.")

    assert len(parsed) == 1
    row = parsed[0]
    assert row.item_name == "peanut butter"
    assert row.quantity is None
    assert row.quantity_label == "Decently filled"
    assert row.unit == "bucket"
    assert row.needed_quantity == "TBD"
    assert row.status == "Needs Review"
    assert row.needs_review is True


def test_voice_parse_container_fullness_common_fractions() -> None:
    parsed = parse_voice_text("one tub of ranch half full. a bottle of olive oil, about a quarter full.")

    assert [(item.item_name, item.quantity, item.quantity_label, item.unit, item.status) for item in parsed] == [
        ("ranch", 0.5, None, "tub", "Partial Quantity"),
        ("olive oil", 0.25, None, "bottle", "Partial Quantity"),
    ]


def test_voice_parse_container_fullness_needed_quantity_stays_separate() -> None:
    parsed = parse_voice_text("a container of pesto mostly full and we need 2 more containers")

    assert len(parsed) == 1
    row = parsed[0]
    assert row.item_name == "pesto"
    assert row.quantity is None
    assert row.quantity_label == "Mostly full"
    assert row.unit == "container"
    assert row.needed_quantity == "2 containers"
    assert row.status == "Needs Review"


def test_voice_parse_container_fullness_almost_empty() -> None:
    parsed = parse_voice_text("a bin of lettuce almost empty")

    assert len(parsed) == 1
    row = parsed[0]
    assert row.item_name == "lettuce"
    assert row.quantity is None
    assert row.quantity_label == "Almost empty"
    assert row.unit == "bin"
    assert row.status == "Needs Review"


def test_voice_parse_exact_bucket_count_stays_numeric() -> None:
    parsed = parse_voice_text("2 buckets of peanut butter")

    assert [(item.item_name, item.quantity, item.quantity_label, item.unit, item.status) for item in parsed] == [
        ("peanut butter", 2, None, "buckets", "Clean"),
    ]
