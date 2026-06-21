import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import InventoryItem
from app.schemas import InventoryItemCreate, InventoryItemRead, InventoryItemUpdate
from app.services.normalization_service import normalize_text
from app.utils.units import normalize_unit


router = APIRouter(prefix="/inventory/items", tags=["inventory"])


def _serialize_item(item: InventoryItem) -> dict:
    data = {
        "id": item.id,
        "restaurant_id": item.restaurant_id,
        "name": item.name,
        "normalized_name": item.normalized_name,
        "category": item.category,
        "default_unit": item.default_unit,
        "aliases": json.loads(item.aliases or "[]"),
        "pack_size": item.pack_size,
        "par_level": item.par_level,
        "vendor": item.vendor,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    return data


def _create_item(payload: InventoryItemCreate) -> InventoryItem:
    return InventoryItem(
        restaurant_id=payload.restaurant_id,
        name=payload.name,
        normalized_name=normalize_text(payload.name),
        category=payload.category,
        default_unit=normalize_unit(payload.default_unit),
        aliases=json.dumps(payload.aliases),
        pack_size=payload.pack_size,
        par_level=payload.par_level,
        vendor=payload.vendor,
    )


@router.post("", response_model=InventoryItemRead)
def create_inventory_item(payload: InventoryItemCreate, db: Session = Depends(get_db)) -> dict:
    item = _create_item(payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


@router.get("", response_model=list[InventoryItemRead])
def list_inventory_items(restaurant_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(InventoryItem).where(InventoryItem.restaurant_id == restaurant_id).order_by(InventoryItem.name))
    return [_serialize_item(item) for item in items]


@router.post("/bulk", response_model=list[InventoryItemRead])
def bulk_create_inventory_items(payload: list[InventoryItemCreate], db: Session = Depends(get_db)) -> list[dict]:
    items = [_create_item(item_payload) for item_payload in payload]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return [_serialize_item(item) for item in items]


@router.get("/{item_id}", response_model=InventoryItemRead)
def get_inventory_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return _serialize_item(item)


@router.put("/{item_id}", response_model=InventoryItemRead)
def update_inventory_item(item_id: int, payload: InventoryItemUpdate, db: Session = Depends(get_db)) -> dict:
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        item.name = data["name"]
        item.normalized_name = normalize_text(data["name"])
    if "default_unit" in data and data["default_unit"] is not None:
        item.default_unit = normalize_unit(data["default_unit"])
    if "aliases" in data and data["aliases"] is not None:
        item.aliases = json.dumps(data["aliases"])
    for field in ("category", "pack_size", "par_level", "vendor"):
        if field in data:
            setattr(item, field, data[field])
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


@router.delete("/{item_id}")
def delete_inventory_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}

