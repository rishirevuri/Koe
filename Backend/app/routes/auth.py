from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import SupabaseUser, get_current_restaurant, get_current_supabase_user
from app.config import get_settings
from app.database import get_db
from app.models import Restaurant
from app.schemas import AuthMeResponse, DevLinkRestaurantRequest, RestaurantRead


router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_me_payload(current_user: SupabaseUser, restaurant: Restaurant) -> dict:
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "restaurant": {"id": restaurant.id, "name": restaurant.name},
    }


@router.get("/me", response_model=AuthMeResponse)
def get_me(
    current_user: SupabaseUser = Depends(get_current_supabase_user),
    restaurant: Restaurant = Depends(get_current_restaurant),
) -> dict:
    return _auth_me_payload(current_user, restaurant)


@router.get("/workspace", response_model=RestaurantRead)
def get_workspace(restaurant: Restaurant = Depends(get_current_restaurant)) -> Restaurant:
    return restaurant


@router.post("/dev-link-restaurant", response_model=RestaurantRead)
def dev_link_restaurant(
    payload: DevLinkRestaurantRequest,
    db: Session = Depends(get_db),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> Restaurant:
    if get_settings().environment != "development":
        raise HTTPException(status_code=403, detail="Development restaurant linking is disabled")

    restaurant_name = payload.restaurant_name.strip()
    if not restaurant_name:
        raise HTTPException(status_code=400, detail="restaurant_name is required")

    restaurant = db.scalar(select(Restaurant).where(Restaurant.name == restaurant_name))
    if restaurant and restaurant.owner_user_id and restaurant.owner_user_id != current_user.user_id:
        raise HTTPException(status_code=409, detail="Restaurant workspace is already linked to another user")

    for owned_restaurant in db.scalars(select(Restaurant).where(Restaurant.owner_user_id == current_user.user_id)):
        if not restaurant or owned_restaurant.id != restaurant.id:
            owned_restaurant.owner_user_id = None
            db.add(owned_restaurant)

    if not restaurant:
        restaurant = Restaurant(name=restaurant_name, location="Tester workspace", owner_user_id=current_user.user_id)
        db.add(restaurant)
    else:
        restaurant.owner_user_id = current_user.user_id
        db.add(restaurant)

    db.commit()
    db.refresh(restaurant)
    return restaurant
