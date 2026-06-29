from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ensure_count_belongs_to_restaurant, ensure_restaurant_id_matches, get_current_restaurant
from app.database import get_db
from app.models import CountEntry, CountSession, Restaurant
from app.schemas import CountEntryCreate, CountEntryRead, CountSessionCreate, CountSessionRead, CountSessionSummary
from app.services.issue_service import create_issue
from app.services.matching_service import match_inventory_item
from app.utils.units import normalize_unit


router = APIRouter(prefix="/counts", tags=["counts"])


def _summary(count: CountSession) -> dict[str, int]:
    return {
        "total_entries": len(count.entries),
        "entries_needing_review": sum(1 for entry in count.entries if entry.needs_review),
    }


@router.post("", response_model=CountSessionRead)
def create_count_session(
    payload: CountSessionCreate,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> CountSession:
    ensure_restaurant_id_matches(payload.restaurant_id, current_restaurant)
    count = CountSession(restaurant_id=current_restaurant.id, area=payload.area, notes=payload.notes)
    db.add(count)
    db.commit()
    db.refresh(count)
    return count


@router.get("", response_model=list[CountSessionRead])
def list_count_sessions(
    restaurant_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> list[CountSession]:
    ensure_restaurant_id_matches(restaurant_id, current_restaurant)
    return list(db.scalars(select(CountSession).where(CountSession.restaurant_id == current_restaurant.id).order_by(CountSession.id)))


@router.get("/{count_id}", response_model=CountSessionSummary)
def get_count_session(
    count_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> dict:
    count = db.get(CountSession, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    return {**CountSessionRead.model_validate(count).model_dump(), "summary": _summary(count)}


@router.post("/{count_id}/entries", response_model=CountEntryRead)
def add_count_entry(
    count_id: int,
    payload: CountEntryCreate,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> CountEntry:
    count = db.get(CountSession, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    match = match_inventory_item(db, count.restaurant_id, payload.item_name)
    entry = CountEntry(
        count_session_id=count.id,
        inventory_item_id=match.matched_item_id,
        item_name=match.matched_name or payload.item_name,
        normalized_item_name=match.normalized_name,
        quantity=payload.quantity,
        unit=normalize_unit(payload.unit),
        area=payload.area or count.area,
        source=payload.source,
        raw_input=payload.raw_input,
        needs_review=match.needs_review,
        review_reason=match.review_reason,
    )
    db.add(entry)
    db.flush()
    if match.needs_review:
        create_issue(
            db,
            restaurant_id=count.restaurant_id,
            count_session_id=count.id,
            count_entry_id=entry.id,
            inventory_item_id=match.matched_item_id,
            issue_type="unknown_item" if match.match_type == "none" else "low_confidence_match",
            title=match.review_reason or "Inventory match needs review",
            description=f"Manual entry '{payload.item_name}' requires review.",
            suggested_action="Confirm the item or add it as an alias.",
        )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/{count_id}/entries", response_model=list[CountEntryRead])
def list_count_entries(
    count_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> list[CountEntry]:
    count = db.get(CountSession, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    return list(db.scalars(select(CountEntry).where(CountEntry.count_session_id == count_id).order_by(CountEntry.id)))


@router.put("/{count_id}/approve", response_model=CountSessionRead)
def approve_count(
    count_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> CountSession:
    count = db.get(CountSession, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    now = datetime.now(timezone.utc)
    count.status = "approved"
    count.completed_at = count.completed_at or now
    count.approved_at = now
    db.add(count)
    db.commit()
    db.refresh(count)
    return count
