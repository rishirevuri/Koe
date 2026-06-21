from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ReportResponse
from app.services.report_service import build_csv, build_report, get_count_or_none


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{count_id}", response_model=ReportResponse)
def get_report(count_id: int, db: Session = Depends(get_db)) -> dict:
    count = get_count_or_none(db, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    return build_report(count)


@router.get("/{count_id}/csv")
def get_report_csv(count_id: int, db: Session = Depends(get_db)) -> Response:
    count = get_count_or_none(db, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    return Response(
        content=build_csv(count),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="koe-count-{count_id}.csv"'},
    )
