from app.utils.text import normalize_text, simple_singular


UNIT_ALIASES = {
    "bottle": "bottles",
    "bottles": "bottles",
    "box": "boxes",
    "boxes": "boxes",
    "case": "cases",
    "cases": "cases",
    "head": "heads",
    "heads": "heads",
    "bag": "bags",
    "bags": "bags",
    "tub": "tubs",
    "tubs": "tubs",
    "container": "containers",
    "containers": "containers",
    "gallon": "gallons",
    "gallons": "gallons",
    "pound": "pounds",
    "pounds": "pounds",
    "lb": "pounds",
    "lbs": "pounds",
    "ounce": "ounces",
    "ounces": "ounces",
    "oz": "ounces",
    "tray": "trays",
    "trays": "trays",
    "crate": "crates",
    "crates": "crates",
}

UNITS_PATTERN = "|".join(sorted(UNIT_ALIASES.keys(), key=len, reverse=True))


def normalize_unit(value: str) -> str:
    normalized = normalize_text(value)
    return UNIT_ALIASES.get(normalized, UNIT_ALIASES.get(simple_singular(normalized), normalized))
