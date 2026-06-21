from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Issue
from app.schemas import IssueRead, IssueResolveRequest
from app.services.issue_service import resolve_issue


router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("", response_model=list[IssueRead])
def list_issues(restaurant_id: int = Query(...), db: Session = Depends(get_db)) -> list[Issue]:
    return list(db.scalars(select(Issue).where(Issue.restaurant_id == restaurant_id).order_by(Issue.id)))


@router.get("/{issue_id}", response_model=IssueRead)
def get_issue(issue_id: int, db: Session = Depends(get_db)) -> Issue:
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.put("/{issue_id}/resolve", response_model=IssueRead)
def resolve_issue_route(issue_id: int, payload: IssueResolveRequest, db: Session = Depends(get_db)) -> Issue:
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return resolve_issue(db, issue, payload.status, payload.resolution_note)
