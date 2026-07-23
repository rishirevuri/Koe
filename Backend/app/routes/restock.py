from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import ensure_count_belongs_to_restaurant, get_current_restaurant
from app.database import get_db
from app.models import CountSession, Restaurant
from app.schemas import RestockPlanResponse
from app.services.restock_planner_service import RestockPlannerError, build_restock_plan


router = APIRouter(prefix="/restock", tags=["restock"])


def _validate_csv_upload(upload: UploadFile, label: str) -> None:
    filename = (upload.filename or "").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{label} must be a CSV file.")


@router.post("/plan", response_model=RestockPlanResponse)
async def create_restock_plan(
    count_id: int = Form(...),
    sales_file: UploadFile = File(...),
    recipe_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> dict:
    count = db.get(CountSession, count_id)
    if not count:
        raise HTTPException(status_code=404, detail="Count session not found")
    ensure_count_belongs_to_restaurant(count.restaurant_id, current_restaurant)

    _validate_csv_upload(sales_file, "Sales data")
    _validate_csv_upload(recipe_file, "Recipe data")

    try:
        sales_bytes = await sales_file.read()
        recipe_bytes = await recipe_file.read()
        return build_restock_plan(count, sales_bytes, recipe_bytes)
    except RestockPlannerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
