from dataclasses import dataclass
import re


PAR_STATUSES = {"sufficient", "low", "critical", "unknown"}
PAR_CONFIDENCES = {"high", "medium", "low"}
REVIEW_STATUSES = {"Needs Review", "Missing Unit", "Possible Duplicate"}


@dataclass(frozen=True)
class ParTarget:
    quantity: float
    unit: str


@dataclass(frozen=True)
class ParRule:
    patterns: tuple[str, ...]
    targets: tuple[ParTarget, ...]
    reason: str
    confidence: str = "medium"


def _target(quantity: float, unit: str) -> ParTarget:
    return ParTarget(quantity=quantity, unit=unit)


PAR_RULES: tuple[ParRule, ...] = (
    # Specific names first so "tomato sauce" does not match "tomatoes".
    ParRule(("roma tomatoes", "roma tomato"), (_target(20, "individual"),), "Common prep produce item for restaurant service.", "medium"),
    ParRule(("tomato sauce",), (_target(12, "cans"),), "Common sauce base with steady restaurant usage.", "medium"),
    ParRule(("water bottles", "bottled water"), (_target(48, "bottles"),), "Common guest-facing beverage item.", "medium"),
    ParRule(("sparkling water",), (_target(48, "bottles"),), "Common bar and table-service beverage item.", "medium"),
    ParRule(("tonic water",), (_target(24, "bottles"),), "Common mixer for bar service.", "medium"),
    ParRule(("ginger beer",), (_target(24, "cans"),), "Common bar mixer with recurring service use.", "medium"),
    ParRule(("coke cans", "coke", "cola"), (_target(24, "cans"),), "Common beverage item with recurring service use.", "medium"),
    ParRule(("2 percent milk", "2 milk"), (_target(3, "gallons"),), "Common dairy item for restaurant prep and drinks.", "medium"),
    ParRule(("whole milk",), (_target(4, "gallons"),), "Common dairy item for restaurant prep and drinks.", "medium"),
    ParRule(("heavy cream",), (_target(2, "gallons"),), "Common dairy item for sauces, coffee, and prep.", "medium"),
    ParRule(("shredded mozzarella",), (_target(8, "bags"),), "Common cheese item for high-turnover prep.", "medium"),
    ParRule(("american cheese",), (_target(40, "slices"),), "Common sandwich and burger service item.", "medium"),
    ParRule(("ground beef",), (_target(15, "pounds"),), "Common high-turnover protein for restaurant service.", "medium"),
    ParRule(("chicken breasts", "chicken breast"), (_target(20, "individual"), _target(30, "pounds")), "Common high-turnover protein for restaurant service.", "medium"),
    ParRule(("sliced turkey",), (_target(8, "pounds"),), "Common deli protein for sandwich prep.", "medium"),
    ParRule(("veggie burger patties", "veggie patties"), (_target(30, "patties"), _target(2, "boxes")), "Common vegetarian entree item.", "medium"),
    ParRule(("pizza dough",), (_target(6, "boxes"),), "Common high-turnover dough item.", "medium"),
    ParRule(("marinara sauce",), (_target(4, "jars"),), "Common sauce item for prep and service.", "medium"),
    ParRule(("burger buns",), (_target(48, "buns"),), "Common high-turnover sandwich item.", "medium"),
    ParRule(("ranch dressing",), (_target(2, "gallons"),), "Common condiment with recurring restaurant usage.", "medium"),
    ParRule(("caesar dressing",), (_target(4, "quarts"),), "Common dressing with recurring restaurant usage.", "medium"),
    ParRule(("receipt paper",), (_target(6, "rolls"),), "Common service supply item.", "medium"),
    ParRule(("paper cups",), (_target(500, "cups"),), "Common disposable supply item.", "medium"),
    ParRule(("takeout containers",), (_target(1, "cases"),), "Common off-premise service supply item.", "medium"),
    ParRule(("frozen fries",), (_target(4, "boxes"),), "Common high-turnover frozen side item.", "medium"),
    ParRule(("frozen berries",), (_target(4, "bags"),), "Common frozen prep item.", "medium"),
    ParRule(("mozzarella sticks",), (_target(2, "boxes"),), "Common frozen appetizer item.", "medium"),
    ParRule(("ice cream",), (_target(3, "tubs"),), "Common dessert item with recurring service use.", "medium"),
    ParRule(("gelato",), (_target(3, "tubs"),), "Common dessert item with recurring service use.", "medium"),
    ParRule(("lemons", "lemon"), (_target(30, "individual"),), "Common high-turnover bar/restaurant garnish item.", "high"),
    ParRule(("limes", "lime"), (_target(40, "individual"),), "Common high-turnover bar/restaurant garnish item.", "high"),
    ParRule(("tomatoes", "tomato"), (_target(24, "individual"),), "Common prep produce item for restaurant service.", "medium"),
    ParRule(("lettuce",), (_target(8, "heads"),), "Common prep produce item for restaurant service.", "medium"),
    ParRule(("cilantro",), (_target(6, "bunches"),), "Common high-turnover garnish and prep item.", "medium"),
    ParRule(("cucumbers", "cucumber"), (_target(6, "individual"), _target(2, "boxes")), "Common prep produce item for restaurant service.", "medium"),
    ParRule(("onions", "onion"), (_target(20, "individual"),), "Common prep produce item for restaurant service.", "medium"),
    ParRule(("avocados", "avocado"), (_target(24, "individual"),), "Common high-turnover prep produce item.", "medium"),
    ParRule(("eggs", "egg"), (_target(120, "eggs"),), "Common breakfast, prep, and baking item.", "high"),
    ParRule(("cheddar",), (_target(4, "blocks"),), "Common cheese item for prep.", "medium"),
    ParRule(("bacon",), (_target(4, "boxes"),), "Common high-turnover protein for restaurant service.", "medium"),
    ParRule(("salmon",), (_target(30, "pounds"),), "Common restaurant protein with meaningful prep demand.", "medium"),
    ParRule(("flour",), (_target(4, "bags"),), "Common baking and prep dry good.", "medium"),
    ParRule(("rice",), (_target(20, "pounds"),), "Common dry good for restaurant prep.", "medium"),
    ParRule(("sugar",), (_target(2, "bags"),), "Common baking and prep dry good.", "medium"),
    ParRule(("pesto",), (_target(4, "containers"),), "Common sauce item for prep and service.", "medium"),
    ParRule(("pickles",), (_target(6, "jars"),), "Common sandwich and burger garnish item.", "medium"),
    ParRule(("sourdough",), (_target(8, "loaves"),), "Common bread item for restaurant prep.", "medium"),
    ParRule(("olive oil",), (_target(3, "bottles"),), "Common cooking and finishing oil.", "medium"),
    ParRule(("canola oil",), (_target(4, "gallons"),), "Common high-use cooking oil.", "medium"),
    ParRule(("napkins", "napkin"), (_target(2, "cases"),), "Common front-of-house supply item.", "medium"),
    ParRule(("straws", "straw"), (_target(1, "boxes"),), "Common beverage service supply item.", "medium"),
)


UNIT_ALIASES = {
    "bag": "bags",
    "bags": "bags",
    "block": "blocks",
    "blocks": "blocks",
    "bottle": "bottles",
    "bottles": "bottles",
    "box": "boxes",
    "boxes": "boxes",
    "bun": "buns",
    "buns": "buns",
    "can": "cans",
    "cans": "cans",
    "case": "cases",
    "cases": "cases",
    "container": "containers",
    "containers": "containers",
    "cup": "cups",
    "cups": "cups",
    "each": "individual",
    "ea": "individual",
    "egg": "eggs",
    "eggs": "eggs",
    "gallon": "gallons",
    "gallons": "gallons",
    "gal": "gallons",
    "head": "heads",
    "heads": "heads",
    "individual": "individual",
    "individuals": "individual",
    "item": "individual",
    "items": "individual",
    "jar": "jars",
    "jars": "jars",
    "lb": "pounds",
    "lbs": "pounds",
    "loaf": "loaves",
    "loaves": "loaves",
    "patties": "patties",
    "patty": "patties",
    "piece": "individual",
    "pieces": "individual",
    "pound": "pounds",
    "pounds": "pounds",
    "quart": "quarts",
    "quarts": "quarts",
    "qt": "quarts",
    "roll": "rolls",
    "rolls": "rolls",
    "slice": "slices",
    "slices": "slices",
    "tub": "tubs",
    "tubs": "tubs",
    "unit": "individual",
    "units": "individual",
    "bunch": "bunches",
    "bunches": "bunches",
    # Common parser outputs where the item name becomes the unit.
    "lemon": "individual",
    "lemons": "individual",
    "lime": "individual",
    "limes": "individual",
    "tomato": "individual",
    "tomatoes": "individual",
    "cucumber": "individual",
    "cucumbers": "individual",
    "onion": "individual",
    "onions": "individual",
    "avocado": "individual",
    "avocados": "individual",
    "breast": "individual",
    "breasts": "individual",
}


def _empty_estimate(reason: str, confidence: str = "low") -> dict:
    return {
        "par_status": "unknown",
        "estimated_par_quantity": None,
        "par_unit": None,
        "par_reason": reason,
        "par_confidence": confidence,
        "is_demo_estimate": True,
    }


def _normalize_text(value: str | None) -> str:
    text = str(value or "").lower().replace("%", " percent ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_unit(value: str | None) -> str:
    return UNIT_ALIASES.get(_normalize_text(value), _normalize_text(value))


def _pattern_matches(item_name: str, pattern: str) -> bool:
    normalized_pattern = _normalize_text(pattern)
    return bool(re.search(rf"(^|\s){re.escape(normalized_pattern)}($|\s)", item_name))


def _find_rule(item_name: str) -> ParRule | None:
    normalized_name = _normalize_text(item_name)
    for rule in PAR_RULES:
        if any(_pattern_matches(normalized_name, pattern) for pattern in rule.patterns):
            return rule
    return None


def estimate_par_status(
    *,
    item_name: str,
    category: str | None = None,
    quantity: float | None,
    unit: str | None,
    status: str | None = None,
) -> dict:
    if status in REVIEW_STATUSES:
        return _empty_estimate("Review item status before comparing to a demo par estimate.")
    if quantity is None:
        return _empty_estimate("Quantity is missing, so this row cannot be compared to an estimated par.")
    try:
        counted_quantity = float(quantity)
    except (TypeError, ValueError):
        return _empty_estimate("Quantity is not numeric, so this row cannot be compared to an estimated par.")
    if not str(unit or "").strip():
        return _empty_estimate("Unit is missing, so this row cannot be safely compared to an estimated par.")

    rule = _find_rule(item_name)
    if not rule:
        category_text = f" in {category}" if category else ""
        return _empty_estimate(f"No safe demo par heuristic exists for this item{category_text} yet.")

    counted_unit = _normalize_unit(unit)
    target = next((candidate for candidate in rule.targets if _normalize_unit(candidate.unit) == counted_unit), None)
    if not target:
        allowed_units = ", ".join(target.unit for target in rule.targets)
        return _empty_estimate(
            f"Counted unit '{unit}' cannot be safely compared with estimated par unit {allowed_units}.",
            rule.confidence,
        )

    if counted_quantity < target.quantity * 0.5:
        par_status = "critical"
    elif counted_quantity < target.quantity:
        par_status = "low"
    else:
        par_status = "sufficient"

    return {
        "par_status": par_status,
        "estimated_par_quantity": target.quantity,
        "par_unit": target.unit,
        "par_reason": f"{rule.reason} Demo estimate based on common restaurant usage patterns.",
        "par_confidence": rule.confidence if rule.confidence in PAR_CONFIDENCES else "low",
        "is_demo_estimate": True,
    }
