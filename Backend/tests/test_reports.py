import csv
import io

from app.models import CountEntry, CountSession, InventoryItem, Restaurant
from app.services.report_service import build_csv, build_report


CSV_HEADER = [
    "Count ID",
    "Restaurant ID",
    "Area",
    "Category",
    "Item Name",
    "Raw Item Name",
    "Quantity",
    "Unit",
    "Quantity to Purchase",
    "Status",
    "Original Phrase",
    "Counted By",
    "Created At",
]


def test_report_summary_and_csv() -> None:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    item = InventoryItem(
        id=1,
        restaurant_id=1,
        name="Olive oil",
        normalized_name="olive oil",
        category="Oils",
        default_unit="bottles",
    )
    count = CountSession(id=1, restaurant_id=1, status="approved", restaurant=restaurant)
    entry = CountEntry(
        id=1,
        count_session_id=1,
        inventory_item_id=1,
        inventory_item=item,
        item_name_raw="olive oil",
        item_name="Olive oil",
        normalized_item_name="olive oil",
        quantity=2.5,
        unit="bottles",
        status="Partial Quantity",
        area="Dry Storage",
        source="voice",
        raw_input="3 bottles olive oil, one half empty",
        original_phrase="3 bottles olive oil, one half empty",
        partial_detail="2 full bottles + 1 half bottle",
        needs_review=False,
        counted_by="tester@example.com",
        needed_quantity="2 bottles",
    )
    count.entries = [entry]

    report = build_report(count)
    assert report["summary"] == {"total_items": 1, "items_needing_review": 0}
    assert report["entries"][0]["item_name_clean"] == "Olive oil"
    assert report["entries"][0]["category"] == "Oils & Liquids"
    assert report["entries"][0]["par_status"] == "low"
    assert report["entries"][0]["estimated_par_quantity"] == 3
    assert report["entries"][0]["par_unit"] == "bottles"
    assert report["entries"][0]["is_demo_estimate"] is True
    csv_text = build_csv(count)
    csv_rows = list(csv.reader(io.StringIO(csv_text)))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][:12] == [
        "1",
        "1",
        "Dry Storage",
        "Oils & Liquids",
        "Olive oil",
        "olive oil",
        "2.5",
        "bottles",
        "2 bottles",
        "Partial Quantity",
        "3 bottles olive oil, one half empty",
        "tester@example.com",
    ]
    assert "par_status" not in csv_text
    assert "Needs Review" not in csv_text
    assert "Manager Note" not in csv_text


def test_csv_blanks_unknown_vague_quantity() -> None:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    count = CountSession(id=1, restaurant_id=1, status="completed", restaurant=restaurant)
    entry = CountEntry(
        id=1,
        count_session_id=1,
        item_name_raw="takeout containers",
        item_name="Takeout containers",
        normalized_item_name="takeout containers",
        category="Supplies",
        quantity=None,
        unit="",
        status="Needs Review",
        area="Storage",
        source="voice",
        raw_input="a few takeout containers, not sure how many",
        original_phrase="a few takeout containers, not sure how many",
        needs_review=True,
        review_reason="Vague or unknown quantity; confirm the count before export.",
        counted_by="tester@example.com",
    )
    count.entries = [entry]

    report = build_report(count)
    assert report["entries"][0]["quantity"] is None
    assert report["entries"][0]["status"] == "Needs Review"
    assert report["entries"][0]["needed_quantity"] == "TBD"

    csv_rows = list(csv.reader(io.StringIO(build_csv(count))))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][:12] == [
        "1",
        "1",
        "Storage",
        "Supplies",
        "Takeout containers",
        "takeout containers",
        "",
        "",
        "TBD",
        "Needs Review",
        "a few takeout containers, not sure how many",
        "tester@example.com",
    ]


def test_csv_exports_qualitative_container_quantity_label() -> None:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    count = CountSession(id=1, restaurant_id=1, status="completed", restaurant=restaurant)
    entry = CountEntry(
        id=1,
        count_session_id=1,
        item_name_raw="peanut butter",
        item_name="Peanut butter",
        normalized_item_name="peanut butter",
        category="Dry Goods",
        quantity=None,
        quantity_label="Decently filled",
        unit="bucket",
        needed_quantity="TBD",
        status="Needs Review",
        area="Dry Storage",
        source="voice",
        raw_input="We have a bucket of peanut butter and it's pretty full.",
        original_phrase="a bucket of peanut butter and it's pretty full",
        needs_review=True,
        review_reason="Qualitative fullness quantity; confirm the exact count before export.",
        counted_by="tester@example.com",
    )
    count.entries = [entry]

    report = build_report(count)
    assert report["entries"][0]["quantity"] == "Decently filled"
    assert report["entries"][0]["quantity_label"] == "Decently filled"
    assert report["entries"][0]["unit"] == "bucket"
    assert report["entries"][0]["needed_quantity"] == "TBD"

    csv_rows = list(csv.reader(io.StringIO(build_csv(count))))
    assert csv_rows[0] == CSV_HEADER
    assert csv_rows[1][:12] == [
        "1",
        "1",
        "Dry Storage",
        "Dry Goods",
        "Peanut butter",
        "peanut butter",
        "Decently filled",
        "bucket",
        "TBD",
        "Needs Review",
        "a bucket of peanut butter and it's pretty full",
        "tester@example.com",
    ]


def test_report_prefers_saved_count_entry_category() -> None:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    item = InventoryItem(
        id=1,
        restaurant_id=1,
        name="Whole milk",
        normalized_name="whole milk",
        category=None,
        default_unit="gallons",
    )
    count = CountSession(id=1, restaurant_id=1, status="completed", restaurant=restaurant)
    entry = CountEntry(
        id=1,
        count_session_id=1,
        inventory_item_id=1,
        inventory_item=item,
        item_name_raw="whole milk",
        item_name="Whole milk",
        normalized_item_name="whole milk",
        category="Dairy & Eggs",
        quantity=10,
        unit="gallons",
        status="Clean",
        area="Walk-in",
        source="voice",
        raw_input="10 gallons of whole milk",
        original_phrase="10 gallons of whole milk",
        needs_review=False,
        counted_by="tester@example.com",
    )
    count.entries = [entry]

    report = build_report(count)

    assert report["entries"][0]["category"] == "Dairy & Eggs"
    assert report["entries"][0]["needed_quantity"] == "TBD"
    assert report["entries"][0]["par_status"] == "sufficient"
    assert report["entries"][0]["estimated_par_quantity"] == 4
