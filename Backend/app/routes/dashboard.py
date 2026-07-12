from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_restaurant
from app.database import get_db
from app.models import CountEntry, CountSession, InventoryItem, Issue, Restaurant


router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Issue types that represent possible duplicate items (kept as a set so new
# duplicate-style issue types can be recognised without code changes elsewhere).
DUPLICATE_ISSUE_TYPES = ("possible_duplicate", "duplicate")
REVIEW_STATUSES = {"Needs Review", "Missing Unit", "Possible Duplicate"}


def _format_quantity(quantity: float) -> str:
    return str(int(quantity)) if float(quantity).is_integer() else str(quantity)


def _entry_needs_review(entry: CountEntry) -> bool:
    return entry.status in REVIEW_STATUSES


def _latest_entry_per_item(entries: list[CountEntry], session_id: int | None = None) -> dict[int, CountEntry]:
    """Map inventory_item_id -> most recent CountEntry. ``entries`` must be
    ordered newest-first. Optionally restrict to a single session."""
    latest: dict[int, CountEntry] = {}
    for entry in entries:
        if session_id is not None and entry.count_session_id != session_id:
            continue
        if entry.inventory_item_id and entry.inventory_item_id not in latest:
            latest[entry.inventory_item_id] = entry
    return latest


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> dict:
    restaurant_id = current_restaurant.id

    # --- Load everything for this restaurant in a few scoped queries ---
    sessions = list(
        db.scalars(
            select(CountSession)
            .where(CountSession.restaurant_id == restaurant_id)
            .order_by(CountSession.started_at.desc(), CountSession.id.desc())
        )
    )
    items = list(db.scalars(select(InventoryItem).where(InventoryItem.restaurant_id == restaurant_id)))
    items_by_id = {item.id: item for item in items}

    session_ids = [session.id for session in sessions]
    entries: list[CountEntry] = []
    if session_ids:
        entries = list(
            db.scalars(
                select(CountEntry)
                .where(CountEntry.count_session_id.in_(session_ids))
                .order_by(CountEntry.created_at.desc(), CountEntry.id.desc())
            )
        )

    # --- 1. Low stock items (latest counted qty below par) ---
    latest_by_item = _latest_entry_per_item(entries)
    low_stock_items = []
    for item in items:
        if item.par_level is None:
            continue
        entry = latest_by_item.get(item.id)
        if entry is None:
            continue  # never counted -> no current quantity to compare
        if entry.quantity < item.par_level:
            low_stock_items.append(
                {
                    "item_name": item.name,
                    "current_quantity": entry.quantity,
                    "unit": entry.unit or item.default_unit,
                    "par_level": item.par_level,
                    "shortfall": round(item.par_level - entry.quantity, 4),
                }
            )
    low_stock_items.sort(key=lambda row: row["shortfall"], reverse=True)

    # --- 2. Last count summary ---
    last_count_summary = None
    if sessions:
        last = sessions[0]
        last_entries = [entry for entry in entries if entry.count_session_id == last.id]
        duration_seconds = None
        if last.completed_at and last.started_at:
            duration_seconds = max(0, int((last.completed_at - last.started_at).total_seconds()))
        last_count_summary = {
            "count_id": last.id,
            "area": last.area,
            "started_at": last.started_at,
            "completed_at": last.completed_at,
            "duration_seconds": duration_seconds,
            "total_items_counted": len(last_entries),
            "needs_review_count": sum(1 for entry in last_entries if _entry_needs_review(entry)),
        }

    # --- 3. Count-over-count changes (two most recent sessions) ---
    count_over_count_changes = []
    if len(sessions) >= 2:
        current_map = _latest_entry_per_item(entries, sessions[0].id)
        previous_map = _latest_entry_per_item(entries, sessions[1].id)
        for item_id in current_map.keys() & previous_map.keys():
            current_entry = current_map[item_id]
            previous_entry = previous_map[item_id]
            delta = current_entry.quantity - previous_entry.quantity
            if delta == 0:
                continue
            item = items_by_id.get(item_id)
            count_over_count_changes.append(
                {
                    "item_name": item.name if item else current_entry.item_name,
                    "previous_quantity": previous_entry.quantity,
                    "current_quantity": current_entry.quantity,
                    "delta": round(delta, 4),
                    "unit": current_entry.unit or (item.default_unit if item else ""),
                }
            )
        count_over_count_changes.sort(key=lambda row: abs(row["delta"]), reverse=True)

    # --- 4. Data quality insights (templated from real data, no AI) ---
    insights: list[str] = []
    recent_session_ids = {session.id for session in sessions[:2]}
    recent_entries = [entry for entry in entries if entry.count_session_id in recent_session_ids]

    if last_count_summary and last_count_summary["needs_review_count"] > 0:
        n = last_count_summary["needs_review_count"]
        insights.append(f"{n} item{'s' if n != 1 else ''} need manager review before export.")

    inconsistent_names: list[str] = []
    seen_inconsistent: set[str] = set()
    for entry in recent_entries:
        item = items_by_id.get(entry.inventory_item_id) if entry.inventory_item_id else None
        if item and entry.unit and item.default_unit and entry.unit != item.default_unit:
            if item.name not in seen_inconsistent:
                seen_inconsistent.add(item.name)
                inconsistent_names.append(item.name)
    for name in inconsistent_names:
        insights.append(f"{name} had inconsistent units across recent counts.")

    seen_partial: set[str] = set()
    for entry in recent_entries:
        if float(entry.quantity).is_integer():
            continue
        item = items_by_id.get(entry.inventory_item_id) if entry.inventory_item_id else None
        name = item.name if item else entry.item_name
        if name in seen_partial:
            continue
        seen_partial.add(name)
        insights.append(
            f"{name} was counted as a partial quantity ({_format_quantity(entry.quantity)} {entry.unit})."
        )

    duplicate_count = (
        db.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.restaurant_id == restaurant_id,
                Issue.issue_type.in_(DUPLICATE_ISSUE_TYPES),
                Issue.status == "open",
            )
        )
        or 0
    )
    if duplicate_count > 0:
        insights.append(
            f"{duplicate_count} possible duplicate item{'s' if duplicate_count != 1 else ''} detected."
        )

    # --- 5. Export status of the most recent count ---
    export_status = {
        "count_id": sessions[0].id if sessions else None,
        "exported": bool(sessions[0].exported) if sessions else False,
    }

    return {
        "low_stock_items": low_stock_items,
        "last_count_summary": last_count_summary,
        "count_over_count_changes": count_over_count_changes,
        "data_quality_insights": insights,
        "export_status": export_status,
    }
