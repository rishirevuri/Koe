import csv
import io
import re

from sqlalchemy.orm import Session

from app.models import CountEntry, CountSession
from app.services.category_service import normalize_inventory_category
from app.services.par_estimate_service import estimate_par_status


REVIEW_STATUSES = {"Needs Review", "Missing Unit", "Possible Duplicate"}
INVALID_EXPORT_ITEM_NAMES = {
    "of",
    "and",
    "then",
    "packs of",
    "cases of",
    "bunches wait no scratch that",
    "is half empty",
    "more on the bottom shelf",
}
UNKNOWN_QUANTITY_PATTERN = re.compile(
    r"\b(?:a few|some|several|vague or unknown quantity|not sure how many|unknown count|(?:i|we)\s+(?:do not|don't)\s+know(?:\s+the)?\s+exact\s+count)\b",
    re.IGNORECASE,
)


def _entry_status(entry: CountEntry) -> str:
    return entry.status or "Clean"


def _entry_quantity(entry: CountEntry, status: str) -> float | None:
    if entry.quantity is None:
        return None
    if entry.quantity == 0 and status in REVIEW_STATUSES:
        text = " ".join(
            str(value or "")
            for value in (entry.review_reason, entry.original_phrase, entry.raw_input)
        )
        if UNKNOWN_QUANTITY_PATTERN.search(text):
            return None
    return entry.quantity


def _entry_needed_quantity(entry: CountEntry) -> str:
    needed_quantity = str(getattr(entry, "needed_quantity", None) or "").strip()
    return needed_quantity or "TBD"


def _entry_row(entry: CountEntry) -> dict:
    status = _entry_status(entry)
    item_name_clean = entry.item_name or (entry.inventory_item.name if entry.inventory_item else "")
    category = normalize_inventory_category(
        item_name_clean,
        entry.category or (entry.inventory_item.category if entry.inventory_item else None),
    )
    quantity = _entry_quantity(entry, status)
    return {
        "count_id": entry.count_session_id,
        "restaurant_id": entry.count_session.restaurant_id,
        "area": entry.area,
        "item_name_raw": entry.item_name_raw or entry.item_name,
        "item_name_clean": item_name_clean,
        "category": category,
        "quantity": quantity,
        "unit": entry.unit,
        "needed_quantity": _entry_needed_quantity(entry),
        "status": status,
        "original_phrase": entry.original_phrase or entry.raw_input or entry.item_name_raw or entry.item_name,
        "created_at": entry.created_at,
        "counted_by": entry.counted_by,
        **estimate_par_status(
            item_name=item_name_clean,
            category=category,
            quantity=quantity,
            unit=entry.unit,
            status=status,
        ),
    }


def _is_exportable_entry(row: dict) -> bool:
    clean_name = " ".join(str(row.get("item_name_clean") or "").lower().strip(" ,.").split())
    raw_name = " ".join(str(row.get("item_name_raw") or "").lower().strip(" ,.").split())
    return clean_name not in INVALID_EXPORT_ITEM_NAMES and raw_name not in INVALID_EXPORT_ITEM_NAMES


def build_report(count: CountSession) -> dict:
    entries = [row for entry in count.entries if _is_exportable_entry(row := _entry_row(entry))]
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
    )
    for entry in build_report(count)["entries"]:
        writer.writerow(
            [
                entry["count_id"],
                entry["restaurant_id"],
                entry["area"] or "",
                entry["category"] or "",
                entry["item_name_clean"],
                entry["item_name_raw"] or "",
                "" if entry["quantity"] is None else entry["quantity"],
                entry["unit"] or "",
                entry["needed_quantity"] or "TBD",
                entry["status"],
                entry["original_phrase"] or "",
                entry["counted_by"] or "",
                entry["created_at"].isoformat() if entry["created_at"] else "",
            ]
        )
    return output.getvalue()


def get_count_or_none(db: Session, count_id: int) -> CountSession | None:
    return db.get(CountSession, count_id)
