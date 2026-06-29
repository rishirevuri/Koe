import csv
import io

from sqlalchemy.orm import Session

from app.models import CountSession


def build_report(count: CountSession) -> dict:
    entries = []
    for entry in count.entries:
        name = entry.inventory_item.name if entry.inventory_item else entry.item_name
        entries.append(
            {
                "name": name,
                "category": entry.inventory_item.category if entry.inventory_item else None,
                "quantity": entry.quantity,
                "unit": entry.unit,
                "area": entry.area,
                "source": entry.source,
                "review_status": "needs_review" if entry.needs_review else "confirmed",
                "raw_input": entry.raw_input,
                "partial_detail": entry.partial_detail,
            }
        )
    return {
        "count_id": count.id,
        "status": count.status,
        "entries": entries,
        "summary": {
            "total_items": len(entries),
            "items_needing_review": sum(1 for entry in count.entries if entry.needs_review),
        },
    }


def build_csv(count: CountSession) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Quantity", "Unit", "Area", "Source", "Review Status", "Raw Input", "Partial Detail"])
    for entry in build_report(count)["entries"]:
        writer.writerow(
            [
                entry["name"],
                entry["quantity"],
                entry["unit"],
                entry["area"] or "",
                entry["source"],
                entry["review_status"],
                entry["raw_input"] or "",
                entry["partial_detail"] or "",
            ]
        )
    return output.getvalue()


def get_count_or_none(db: Session, count_id: int) -> CountSession | None:
    return db.get(CountSession, count_id)
