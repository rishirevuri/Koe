from app.models import CountEntry, CountSession, InventoryItem, Restaurant
from app.services.report_service import build_csv, build_report


def test_report_summary_and_csv() -> None:
    restaurant = Restaurant(id=1, name="Demo Restaurant")
    item = InventoryItem(id=1, restaurant_id=1, name="Olive oil", normalized_name="olive oil", default_unit="bottles")
    count = CountSession(id=1, restaurant_id=1, status="approved", restaurant=restaurant)
    entry = CountEntry(
        id=1,
        count_session_id=1,
        inventory_item_id=1,
        inventory_item=item,
        item_name="Olive oil",
        normalized_item_name="olive oil",
        quantity=2.5,
        unit="bottles",
        area="Dry Storage",
        source="voice",
        raw_input="3 bottles olive oil, one half empty",
        partial_detail="2 full bottles + 1 half bottle",
        needs_review=False,
    )
    count.entries = [entry]

    report = build_report(count)
    assert report["summary"] == {"total_items": 1, "items_needing_review": 0}
    assert report["entries"][0]["name"] == "Olive oil"
    assert "Olive oil,2.5,bottles,Dry Storage,voice,confirmed" in build_csv(count)
