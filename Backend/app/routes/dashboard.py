from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_restaurant
from app.database import get_db
from app.models import CountEntry, CountSession, InventoryItem, Issue, Restaurant
from app.services.par_estimate_service import estimate_par_status


router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Issue types that represent possible duplicate items (kept as a set so new
# duplicate-style issue types can be recognised without code changes elsewhere).
DUPLICATE_ISSUE_TYPES = ("possible_duplicate", "duplicate")
REVIEW_STATUSES = {"Needs Review", "Missing Unit", "Possible Duplicate"}


def _format_quantity(quantity: float | None) -> str:
    if quantity is None:
        return ""
    return str(int(quantity)) if float(quantity).is_integer() else str(quantity)


def _entry_needs_review(entry: CountEntry) -> bool:
    return entry.status in REVIEW_STATUSES


def _entry_name(entry: CountEntry) -> str:
    return entry.inventory_item.name if entry.inventory_item else entry.item_name


def _entry_category(entry: CountEntry) -> str | None:
    return entry.category or (entry.inventory_item.category if entry.inventory_item else None)


def _par_row(entry: CountEntry) -> dict:
    status = entry.status or "Clean"
    item_name = _entry_name(entry)
    estimate = estimate_par_status(
        item_name=item_name,
        category=_entry_category(entry),
        quantity=entry.quantity,
        unit=entry.unit,
        status=status,
    )
    return {
        "item_name": item_name,
        "quantity": entry.quantity,
        "unit": entry.unit,
        **estimate,
    }


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
        if entry.quantity is None:
            continue
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
    last_entries: list[CountEntry] = []
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
            if current_entry.quantity is None or previous_entry.quantity is None:
                continue
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
        if entry.quantity is None:
            continue
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

    # --- 5. Demo restaurant-aware par estimates for the latest count ---
    estimated_par_rows = [_par_row(entry) for entry in last_entries]
    critical_count = sum(1 for row in estimated_par_rows if row["par_status"] == "critical")
    low_count = sum(1 for row in estimated_par_rows if row["par_status"] == "low")
    unknown_count = sum(1 for row in estimated_par_rows if row["par_status"] == "unknown")
    estimated_reorder_watchlist = [
        row for row in estimated_par_rows if row["par_status"] in {"critical", "low"}
    ]
    status_rank = {"critical": 0, "low": 1}
    estimated_reorder_watchlist.sort(
        key=lambda row: (
            status_rank.get(row["par_status"], 9),
            -(
                (row["estimated_par_quantity"] - row["quantity"]) / row["estimated_par_quantity"]
                if row["estimated_par_quantity"]
                else 0
            ),
            row["item_name"],
        )
    )
    if estimated_par_rows:
        if critical_count:
            insights.append(
                f"{critical_count} critical reorder candidate{'s' if critical_count != 1 else ''} based on demo estimated par."
            )
        if low_count:
            insights.append(
                f"{low_count} item{'s' if low_count != 1 else ''} below estimated par based on common restaurant usage patterns."
            )
        insights.append("Demo par estimates enabled; review before ordering.")

    # --- 6. Export status of the most recent count ---
    export_status = {
        "count_id": sessions[0].id if sessions else None,
        "exported": bool(sessions[0].exported) if sessions else False,
    }

    return {
        "low_stock_items": low_stock_items,
        "last_count_summary": last_count_summary,
        "count_over_count_changes": count_over_count_changes,
        "data_quality_insights": insights,
        "estimated_par_summary": {
            "critical_items": critical_count,
            "low_items": low_count,
            "unknown_items": unknown_count,
            "watchlist_items": critical_count + low_count,
            "is_demo_estimate": True,
        },
        "estimated_reorder_watchlist": estimated_reorder_watchlist,
        "export_status": export_status,
    }
