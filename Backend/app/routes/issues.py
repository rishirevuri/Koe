from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ensure_restaurant_id_matches, get_current_restaurant
from app.database import get_db
from app.models import Issue, Restaurant
from app.schemas import IssueRead, IssueResolveRequest
from app.services.issue_service import resolve_issue


router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("", response_model=list[IssueRead])
def list_issues(
    restaurant_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> list[Issue]:
    ensure_restaurant_id_matches(restaurant_id, current_restaurant)
    return list(db.scalars(select(Issue).where(Issue.restaurant_id == current_restaurant.id).order_by(Issue.id)))


@router.get("/{issue_id}", response_model=IssueRead)
def get_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> Issue:
    issue = db.get(Issue, issue_id)
    if not issue or issue.restaurant_id != current_restaurant.id:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.put("/{issue_id}/resolve", response_model=IssueRead)
def resolve_issue_route(
    issue_id: int,
    payload: IssueResolveRequest,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> Issue:
    issue = db.get(Issue, issue_id)
    if not issue or issue.restaurant_id != current_restaurant.id:
        raise HTTPException(status_code=404, detail="Issue not found")
    return resolve_issue(db, issue, payload.status, payload.resolution_note)
