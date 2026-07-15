import pytest

from app.services.category_service import normalize_inventory_category


@pytest.mark.parametrize(
    ("item_name", "expected"),
    [
        ("marinara sauce", "Sauces & Condiments"),
        ("pesto", "Sauces & Condiments"),
        ("tomato sauce", "Sauces & Condiments"),
        ("ranch dressing", "Sauces & Condiments"),
        ("Caesar dressing", "Sauces & Condiments"),
        ("pickles", "Sauces & Condiments"),
        ("olive oil", "Oils & Liquids"),
        ("canola oil", "Oils & Liquids"),
        ("water bottles", "Beverages"),
        ("sparkling water", "Beverages"),
        ("tonic water", "Beverages"),
        ("ginger beer", "Beverages"),
        ("coke cans", "Beverages"),
        ("cola", "Beverages"),
        ("burger buns", "Bakery"),
        ("hamburger buns", "Bakery"),
        ("sourdough bread", "Bakery"),
        ("bacon", "Proteins"),
        ("salmon", "Proteins"),
        ("chicken breast", "Proteins"),
        ("turkey", "Proteins"),
        ("veggie burger patties", "Proteins"),
        ("frozen fries", "Frozen"),
        ("frozen berries", "Frozen"),
        ("ice cream", "Frozen"),
        ("mozzarella sticks", "Frozen"),
        ("napkins", "Supplies"),
        ("paper cups", "Supplies"),
        ("takeout containers", "Supplies"),
        ("receipt paper", "Supplies"),
        ("flour", "Dry Goods"),
        ("rice", "Dry Goods"),
        ("sugar", "Dry Goods"),
        ("pizza dough", "Dry Goods"),
    ],
)
def test_restaurant_category_mapping(item_name: str, expected: str) -> None:
    assert normalize_inventory_category(item_name, "Dry Goods") == expected


@pytest.mark.parametrize(
    ("legacy_category", "expected"),
    [
        ("Meats", "Proteins"),
        ("Meat", "Proteins"),
        ("Liquids", "Oils & Liquids"),
        ("Bar", "Beverages"),
        ("Other", "Uncategorized"),
        ("Oils", "Oils & Liquids"),
        ("Dairy", "Dairy & Eggs"),
    ],
)
def test_legacy_category_labels_are_normalized(legacy_category: str, expected: str) -> None:
    assert normalize_inventory_category("unknown row", legacy_category) == expected
