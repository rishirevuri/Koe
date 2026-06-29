from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import SupabaseUser, ensure_restaurant_id_matches, get_current_restaurant, get_current_supabase_user
from app.database import get_db
from app.models import Restaurant
from app.schemas import RestaurantCreate, RestaurantRead


router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantRead)
def create_restaurant(
    payload: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> Restaurant:
    data = payload.model_dump()
    data["owner_user_id"] = current_user.user_id
    restaurant = Restaurant(**data)
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


@router.get("", response_model=list[RestaurantRead])
def list_restaurants(current_restaurant: Restaurant = Depends(get_current_restaurant)) -> list[Restaurant]:
    return [current_restaurant]


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def get_restaurant(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_restaurant: Restaurant = Depends(get_current_restaurant),
) -> Restaurant:
    ensure_restaurant_id_matches(restaurant_id, current_restaurant)
    restaurant = db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant
