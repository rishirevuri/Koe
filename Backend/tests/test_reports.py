from app.models import CountEntry, CountSession, InventoryItem, Restaurant
from app.services.report_service import build_csv, build_report


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
    )
    count.entries = [entry]

    report = build_report(count)
    assert report["summary"] == {"total_items": 1, "items_needing_review": 0}
    assert report["entries"][0]["item_name_clean"] == "Olive oil"
    assert report["entries"][0]["category"] == "Oils"
    csv_text = build_csv(count)
    assert "Count ID,Restaurant ID,Area,Raw Item Name,Clean Item Name,Quantity,Unit,Status,Original Phrase,Created At,Counted By" in csv_text
    assert "1,1,Dry Storage,olive oil,Olive oil,2.5,bottles,Partial Quantity" in csv_text
    assert "Needs Review" not in csv_text
    assert "Manager Note" not in csv_text
