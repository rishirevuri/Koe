from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Restaurant


@dataclass(frozen=True)
class SupabaseUser:
    user_id: str
    email: str | None = None


def get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return token.strip()


@lru_cache(maxsize=1)
def _get_supabase_client():
    settings = get_settings()
    key = (
        settings.supabase_anon_key
        if settings._has_real_value(settings.supabase_anon_key)
        else settings.supabase_service_role_key
    )
    if not settings._has_real_value(settings.supabase_url) or not settings._has_real_value(key):
        raise HTTPException(status_code=500, detail="Supabase Auth is not configured")

    try:
        from supabase import create_client
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Supabase Python client is not installed") from exc

    return create_client(settings.supabase_url, key)


def get_current_supabase_user(token: str = Depends(get_bearer_token)) -> SupabaseUser:
    try:
        response = _get_supabase_client().auth.get_user(token)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc

    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token")

    return SupabaseUser(user_id=user_id, email=getattr(user, "email", None))


def get_current_restaurant(
    db: Session = Depends(get_db),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
    selected_restaurant_id: int | None = Header(default=None, alias="X-Restaurant-Id"),
) -> Restaurant:
    query = select(Restaurant).where(Restaurant.owner_user_id == current_user.user_id)
    if selected_restaurant_id is not None:
        query = query.where(Restaurant.id == selected_restaurant_id)
    restaurant = db.scalar(query.order_by(Restaurant.id))
    if not restaurant:
        raise HTTPException(status_code=404, detail="No restaurant workspace found for this user.")
    return restaurant


def ensure_restaurant_id_matches(payload_restaurant_id: int | None, restaurant: Restaurant) -> None:
    if payload_restaurant_id is not None and payload_restaurant_id != restaurant.id:
        raise HTTPException(status_code=403, detail="Restaurant does not belong to this user")


def ensure_count_belongs_to_restaurant(count_restaurant_id: int, restaurant: Restaurant) -> None:
    if count_restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Count session not found")
