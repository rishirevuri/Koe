import json
from pathlib import Path

from app.config import BASE_DIR, get_settings
from app.database import Base, SessionLocal, engine
from app.models import InventoryItem, Restaurant
from app.services.normalization_service import normalize_text
from app.utils.units import normalize_unit


SEED_ITEMS = [
    ("Olive oil", "Oils", "bottles", ["EVOO", "extra virgin olive oil", "olive oil bottle"], 6),
    ("Lettuce", "Produce", "heads", ["lettuce heads", "romaine", "romaine lettuce"], 10),
    ("Tomatoes", "Produce", "boxes", ["tomato", "tomato boxes", "roma tomatoes"], 8),
    ("Cheese", "Dairy", "boxes", ["cheese box", "cheese boxes"], 5),
    ("Chicken breast", "Meat", "cases", ["chicken", "chix breast", "chicken case"], 7),
    ("Pellegrino", "Beverages", "cases", ["san pellegrino", "sparkling water"], 4),
]

SEED_RESTAURANTS = [
    ("Demo Restaurant", "Local Demo"),
    ("Smoking Pig BBQ", "Tester sample starter inventory"),
    ("Massimo’s", "Tester sample starter inventory"),
]


def seed(reset: bool = True) -> None:
    settings = get_settings()
    if reset and settings.is_production:
        raise RuntimeError("Refusing to reset seed data in production.")
    Path(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        restaurants: list[Restaurant] = []
        for restaurant_name, location in SEED_RESTAURANTS:
            restaurant = Restaurant(name=restaurant_name, location=location, owner_user_id=None)
            db.add(restaurant)
            db.flush()
            restaurants.append(restaurant)
            for name, category, unit, aliases, par_level in SEED_ITEMS:
                db.add(
                    InventoryItem(
                        restaurant_id=restaurant.id,
                        name=name,
                        normalized_name=normalize_text(name),
                        category=category,
                        default_unit=normalize_unit(unit),
                        aliases=json.dumps(aliases),
                        par_level=par_level,
                    )
                )
        db.commit()
        seeded = ", ".join(f"{restaurant.name} id={restaurant.id}" for restaurant in restaurants)
        print(f"Seeded sample starter inventory for {seeded}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
