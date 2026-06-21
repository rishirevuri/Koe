import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryItem
from app.services.normalization_service import normalize_text
from app.utils.text import simple_singular


@dataclass
class MatchResult:
    matched_item_id: int | None
    matched_name: str | None
    normalized_name: str
    match_type: str
    needs_review: bool
    review_reason: str | None


def _aliases(item: InventoryItem) -> list[str]:
    try:
        value = json.loads(item.aliases or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _tokens(value: str) -> set[str]:
    return {simple_singular(token) for token in normalize_text(value).split() if len(token) > 2}


def match_inventory_item(db: Session, restaurant_id: int, raw_item_name: str) -> MatchResult:
    normalized = normalize_text(raw_item_name)
    items = list(db.scalars(select(InventoryItem).where(InventoryItem.restaurant_id == restaurant_id)))

    for item in items:
        if item.normalized_name == normalized:
            return MatchResult(item.id, item.name, normalized, "exact", False, None)

    for item in items:
        for alias in _aliases(item):
            if normalize_text(alias) == normalized:
                return MatchResult(item.id, item.name, normalized, "alias", False, None)

    raw_tokens = _tokens(normalized)
    best: tuple[InventoryItem, float] | None = None
    for item in items:
        candidates = [item.normalized_name, *_aliases(item)]
        for candidate in candidates:
            candidate_norm = normalize_text(candidate)
            if candidate_norm in normalized or normalized in candidate_norm:
                return MatchResult(
                    item.id,
                    item.name,
                    normalized,
                    "fuzzy",
                    item.normalized_name != normalized,
                    f"Possible fuzzy match to {item.name}",
                )
            candidate_tokens = _tokens(candidate_norm)
            if not candidate_tokens:
                continue
            score = len(raw_tokens & candidate_tokens) / len(raw_tokens | candidate_tokens)
            if score >= 0.45 and (best is None or score > best[1]):
                best = (item, score)

    if best:
        item = best[0]
        return MatchResult(item.id, item.name, normalized, "fuzzy", True, f"Low confidence fuzzy match to {item.name}")

    return MatchResult(None, None, normalized, "none", True, f"Unknown item: {raw_item_name}")
