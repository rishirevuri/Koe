from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue


def create_issue(
    db: Session,
    *,
    restaurant_id: int,
    issue_type: str,
    title: str,
    description: str,
    count_session_id: int | None = None,
    inventory_item_id: int | None = None,
    count_entry_id: int | None = None,
    suggested_action: str | None = None,
) -> Issue:
    existing = db.scalar(
        select(Issue).where(
            Issue.restaurant_id == restaurant_id,
            Issue.issue_type == issue_type,
            Issue.title == title,
            Issue.status == "open",
            Issue.count_session_id == count_session_id,
            Issue.count_entry_id == count_entry_id,
        )
    )
    if existing:
        return existing

    issue = Issue(
        restaurant_id=restaurant_id,
        count_session_id=count_session_id,
        inventory_item_id=inventory_item_id,
        count_entry_id=count_entry_id,
        issue_type=issue_type,
        title=title,
        description=description,
        suggested_action=suggested_action,
    )
    db.add(issue)
    return issue


def resolve_issue(db: Session, issue: Issue, status: str = "resolved", resolution_note: str | None = None) -> Issue:
    issue.status = status
    issue.resolved_at = datetime.now(timezone.utc) if status == "resolved" else None
    if resolution_note:
        issue.description = f"{issue.description}\n\nResolution note: {resolution_note}"
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue
