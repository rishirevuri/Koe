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
    "pack": "packs",
    "packs": "packs",
    "bunch": "bunches",
    "bunches": "bunches",
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
    "gram": "grams",
    "grams": "grams",
    "g": "grams",
    "milligram": "milligrams",
    "milligrams": "milligrams",
    "mg": "milligrams",
    "kilogram": "kilograms",
    "kilograms": "kilograms",
    "kg": "kilograms",
    "tray": "trays",
    "trays": "trays",
    "crate": "crates",
    "crates": "crates",
    "carton": "cartons",
    "cartons": "cartons",
    "cartridge": "cartridges",
    "cartridges": "cartridges",
    "individual": "individual",
    "individuals": "individual",
}

UNITS_PATTERN = "|".join(sorted(UNIT_ALIASES.keys(), key=len, reverse=True))


def normalize_unit(value: str) -> str:
    normalized = normalize_text(value)
    return UNIT_ALIASES.get(normalized, UNIT_ALIASES.get(simple_singular(normalized), normalized))
