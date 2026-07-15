from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import SupabaseUser, ensure_restaurant_id_matches, get_current_restaurant, get_current_supabase_user
from app.database import get_db
from app.models import Restaurant
from app.schemas import RestaurantCreate, RestaurantRead


router = APIRouter(prefix="/restaurants", tags=["restaurants"])


def _clean_restaurant_name(name: str) -> str:
    return " ".join(name.strip().split())


@router.post("", response_model=RestaurantRead)
def create_restaurant(
    payload: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> Restaurant:
    restaurant_name = _clean_restaurant_name(payload.name)
    if not restaurant_name:
        raise HTTPException(status_code=400, detail="Restaurant name is required")

    normalized_name = restaurant_name.lower()
    owned_restaurant = db.scalar(
        select(Restaurant)
        .where(
            Restaurant.owner_user_id == current_user.user_id,
            func.lower(Restaurant.name) == normalized_name,
        )
        .order_by(Restaurant.id)
    )
    if owned_restaurant:
        return owned_restaurant

    unclaimed_restaurant = db.scalar(
        select(Restaurant)
        .where(
            Restaurant.owner_user_id.is_(None),
            func.lower(Restaurant.name) == normalized_name,
        )
        .order_by(Restaurant.id)
    )
    if unclaimed_restaurant:
        unclaimed_restaurant.owner_user_id = current_user.user_id
        if payload.location:
            unclaimed_restaurant.location = payload.location
        db.add(unclaimed_restaurant)
        db.commit()
        db.refresh(unclaimed_restaurant)
        return unclaimed_restaurant

    restaurant = Restaurant(name=restaurant_name, location=payload.location, owner_user_id=current_user.user_id)
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


@router.get("", response_model=list[RestaurantRead])
def list_restaurants(
    db: Session = Depends(get_db),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> list[Restaurant]:
    return list(
        db.scalars(select(Restaurant).where(Restaurant.owner_user_id == current_user.user_id).order_by(Restaurant.id))
    )


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
