import csv
import io

from sqlalchemy.orm import Session

from app.models import CountEntry, CountSession


REVIEW_STATUSES = {"Needs Review", "Missing Unit", "Possible Duplicate"}


def _entry_status(entry: CountEntry) -> str:
    return entry.status or "Clean"


def _entry_row(entry: CountEntry) -> dict:
    return {
        "count_id": entry.count_session_id,
        "restaurant_id": entry.count_session.restaurant_id,
        "area": entry.area,
        "item_name_raw": entry.item_name_raw or entry.item_name,
        "item_name_clean": entry.inventory_item.name if entry.inventory_item else entry.item_name,
        "quantity": entry.quantity,
        "unit": entry.unit,
        "status": _entry_status(entry),
        "original_phrase": entry.original_phrase or entry.raw_input or entry.item_name_raw or entry.item_name,
        "created_at": entry.created_at,
        "counted_by": entry.counted_by,
    }


def build_report(count: CountSession) -> dict:
    entries = [_entry_row(entry) for entry in count.entries]
    return {
        "count_id": count.id,
        "status": count.status,
        "entries": entries,
        "summary": {
            "total_items": len(entries),
            "items_needing_review": sum(1 for entry in entries if entry["status"] in REVIEW_STATUSES),
        },
    }


def build_csv(count: CountSession) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Count ID",
            "Restaurant ID",
            "Area",
            "Raw Item Name",
            "Clean Item Name",
            "Quantity",
            "Unit",
            "Status",
            "Original Phrase",
            "Created At",
            "Counted By",
        ]
    )
    for entry in build_report(count)["entries"]:
        writer.writerow(
            [
                entry["count_id"],
                entry["restaurant_id"],
                entry["area"] or "",
                entry["item_name_raw"] or "",
                entry["item_name_clean"],
                entry["quantity"],
                entry["unit"],
                entry["status"],
                entry["original_phrase"] or "",
                entry["created_at"].isoformat() if entry["created_at"] else "",
                entry["counted_by"] or "",
            ]
        )
    return output.getvalue()


def get_count_or_none(db: Session, count_id: int) -> CountSession | None:
    return db.get(CountSession, count_id)
