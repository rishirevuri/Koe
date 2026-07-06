from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import ensure_count_belongs_to_restaurant, get_current_restaurant
from app.database import get_db
from app.models import Restaurant
from app.schemas import ReportResponse
from app.services.report_service import build_csv, build_report, get_count_or_none


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{count_id}", response_model=ReportResponse)
def get_report(
    count_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> dict:
    count = get_count_or_none(db, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    return build_report(count)


@router.get("/{count_id}/csv")
def get_report_csv(
    count_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> Response:
    count = get_count_or_none(db, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)
    csv_content = build_csv(count)
    if not count.exported:
        count.exported = True
        db.add(count)
        db.commit()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="koe-count-{count_id}.csv"'},
    )
