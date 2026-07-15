import re


CATEGORY_LABELS = {
    "Produce",
    "Dairy & Eggs",
    "Proteins",
    "Bakery",
    "Sauces & Condiments",
    "Oils & Liquids",
    "Beverages",
    "Frozen",
    "Supplies",
    "Dry Goods",
    "Uncategorized",
}

CATEGORY_ALIASES = {
    "bar": "Beverages",
    "beverage": "Beverages",
    "beverages": "Beverages",
    "condiment": "Sauces & Condiments",
    "condiments": "Sauces & Condiments",
    "dairy": "Dairy & Eggs",
    "dairy and eggs": "Dairy & Eggs",
    "dairy eggs": "Dairy & Eggs",
    "dry": "Dry Goods",
    "dry goods": "Dry Goods",
    "frozen": "Frozen",
    "liquid": "Oils & Liquids",
    "liquids": "Oils & Liquids",
    "meat": "Proteins",
    "meats": "Proteins",
    "oil": "Oils & Liquids",
    "oils": "Oils & Liquids",
    "oils and liquids": "Oils & Liquids",
    "other": "Uncategorized",
    "produce": "Produce",
    "protein": "Proteins",
    "proteins": "Proteins",
    "sauces": "Sauces & Condiments",
    "sauces and condiments": "Sauces & Condiments",
    "supplies": "Supplies",
    "supply": "Supplies",
}

CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    (r"\b(?:marinara sauce|tomato sauce|pesto|ranch dressing|caesar dressing|pickles?)\b", "Sauces & Condiments"),
    (r"\b(?:olive oil|canola oil|oil|vinegar)\b", "Oils & Liquids"),
    (r"\b(?:water bottles?|bottled water|sparkling water|tonic waters?|ginger beers?|coke cans?|coke|cola)\b", "Beverages"),
    (r"\b(?:whole milk|2 percent milk|two percent milk|heavy cream|cheese|eggs?)\b", "Dairy & Eggs"),
    (r"\b(?:hamburger buns?|burger buns?|sourdough|bread)\b", "Bakery"),
    (r"\b(?:chicken|beef|ground beef|bacon|salmon|turkey|patties?|chicken breasts?|chicken wings?)\b", "Proteins"),
    (r"\b(?:frozen fries|frozen berries|ice cream|gelato|mozzarella sticks)\b", "Frozen"),
    (r"\b(?:napkins?|straws?|receipt paper|paper cups?|takeout containers?)\b", "Supplies"),
    (r"\b(?:tomatoes?|lettuce|cucumbers?|cilantro|onions?|avocados?|lemons?|limes?|roma tomatoes?)\b", "Produce"),
    (r"\b(?:flour|rice|sugar|pizza dough|pasta)\b", "Dry Goods"),
)


def _normalize_text(value: str | None) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_inventory_category(item_name: str | None, category: str | None = None) -> str:
    normalized_name = _normalize_text(item_name)
    for pattern, label in CATEGORY_RULES:
        if re.search(pattern, normalized_name):
            return label

    raw_category = str(category or "").strip()
    if raw_category in CATEGORY_LABELS:
        return raw_category

    normalized_category = _normalize_text(raw_category)
    return CATEGORY_ALIASES.get(normalized_category, "Uncategorized")
