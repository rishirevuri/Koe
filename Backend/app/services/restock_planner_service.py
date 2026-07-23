import csv
import io
from dataclasses import dataclass, field

from app.models import CountEntry, CountSession
from app.utils.text import normalize_text, simple_singular
from app.utils.units import normalize_unit


SAFETY_BUFFER_PERCENT = 10
MAX_CSV_BYTES = 2 * 1024 * 1024


class RestockPlannerError(ValueError):
    pass


@dataclass
class SalesRow:
    item_name: str
    quantity_sold: float


@dataclass
class RecipeRow:
    menu_item: str
    ingredient_name: str
    quantity_per_item: float
    unit: str


@dataclass
class IngredientDemand:
    ingredient: str
    unit: str
    projected_need: float = 0
    sources: list[dict] = field(default_factory=list)


@dataclass
class StockMatch:
    item_name: str | None
    quantity: float | None
    unit: str | None
    status: str


COUNT_UNIT_ALIASES = {
    "count": "count",
    "counts": "count",
    "each": "count",
    "ea": "count",
    "individual": "count",
    "individuals": "count",
    "unit": "count",
    "units": "count",
    "bun": "buns",
    "buns": "buns",
    "cup": "cups",
    "cups": "cups",
    "egg": "eggs",
    "eggs": "eggs",
    "patty": "patties",
    "patties": "patties",
    "bottle": "bottles",
    "bottles": "bottles",
    "can": "cans",
    "cans": "cans",
}


def _round_quantity(value: float) -> float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def _canonical_name(value: str | None) -> str:
    normalized = normalize_text(value or "")
    return " ".join(simple_singular(token) for token in normalized.split())


def _canonical_unit(value: str | None) -> str:
    normalized = normalize_unit(value or "")
    return COUNT_UNIT_ALIASES.get(normalized, normalized)


def _display_name(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned or "Unnamed ingredient"


def _header_key(value: str | None) -> str:
    return "".join(character for character in normalize_text(value or "") if character.isalnum())


def _parse_float(value: str | float | int | None, *, field_name: str, row_number: int, label: str) -> float:
    raw = str(value if value is not None else "").strip().replace(",", "")
    if not raw:
        raise RestockPlannerError(f"{label} row {row_number} is missing {field_name}.")
    try:
        return float(raw)
    except ValueError as exc:
        raise RestockPlannerError(f"{label} row {row_number} has invalid {field_name}.") from exc


def _read_csv_rows(data: bytes, *, label: str, required_columns: list[str]) -> list[dict[str, str]]:
    if not data:
        raise RestockPlannerError(f"{label} CSV is empty.")
    if len(data) > MAX_CSV_BYTES:
        raise RestockPlannerError(f"{label} CSV is too large. Upload a file under 2 MB.")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RestockPlannerError(f"{label} CSV must be UTF-8 text.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RestockPlannerError(f"{label} CSV is missing a header row.")

    header_lookup = {_header_key(header): header for header in reader.fieldnames}
    missing = [column for column in required_columns if _header_key(column) not in header_lookup]
    if missing:
        raise RestockPlannerError(f"Missing required {label.lower()} columns: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        rows.append(
            {
                column: str(raw_row.get(header_lookup[_header_key(column)]) or "").strip()
                for column in required_columns
            }
        )
    if not rows:
        raise RestockPlannerError(f"{label} CSV has no data rows.")
    return rows


def parse_sales_csv(data: bytes) -> list[SalesRow]:
    rows = _read_csv_rows(data, label="Sales", required_columns=["item_name", "quantity_sold"])
    parsed: list[SalesRow] = []
    for index, row in enumerate(rows, start=2):
        item_name = row["item_name"].strip()
        if not item_name:
            raise RestockPlannerError(f"Sales row {index} is missing item_name.")
        parsed.append(
            SalesRow(
                item_name=item_name,
                quantity_sold=_parse_float(row["quantity_sold"], field_name="quantity_sold", row_number=index, label="Sales"),
            )
        )
    return parsed


def parse_recipe_csv(data: bytes) -> list[RecipeRow]:
    rows = _read_csv_rows(
        data,
        label="Recipe",
        required_columns=["menu_item", "ingredient_name", "quantity_per_item", "unit"],
    )
    parsed: list[RecipeRow] = []
    for index, row in enumerate(rows, start=2):
        menu_item = row["menu_item"].strip()
        ingredient_name = row["ingredient_name"].strip()
        unit = row["unit"].strip()
        if not menu_item:
            raise RestockPlannerError(f"Recipe row {index} is missing menu_item.")
        if not ingredient_name:
            raise RestockPlannerError(f"Recipe row {index} is missing ingredient_name.")
        if not unit:
            raise RestockPlannerError(f"Recipe row {index} is missing unit.")
        parsed.append(
            RecipeRow(
                menu_item=menu_item,
                ingredient_name=ingredient_name,
                quantity_per_item=_parse_float(
                    row["quantity_per_item"],
                    field_name="quantity_per_item",
                    row_number=index,
                    label="Recipe",
                ),
                unit=_canonical_unit(unit),
            )
        )
    return parsed


def _sales_by_menu_item(rows: list[SalesRow]) -> dict[str, float]:
    sales: dict[str, float] = {}
    for row in rows:
        key = _canonical_name(row.item_name)
        sales[key] = sales.get(key, 0) + row.quantity_sold
    return sales


def _build_ingredient_demands(sales_rows: list[SalesRow], recipe_rows: list[RecipeRow]) -> list[IngredientDemand]:
    sales = _sales_by_menu_item(sales_rows)
    demands: dict[tuple[str, str], IngredientDemand] = {}
    for row in recipe_rows:
        monthly_sales = sales.get(_canonical_name(row.menu_item), 0)
        if monthly_sales <= 0:
            continue
        weekly_sales = monthly_sales / 4
        projected_need = weekly_sales * row.quantity_per_item
        ingredient_key = _canonical_name(row.ingredient_name)
        demand_key = (ingredient_key, row.unit)
        if demand_key not in demands:
            demands[demand_key] = IngredientDemand(ingredient=_display_name(row.ingredient_name), unit=row.unit)
        demand = demands[demand_key]
        demand.projected_need += projected_need
        demand.sources.append(
            {
                "menu_item": _display_name(row.menu_item),
                "weekly_sales": _round_quantity(weekly_sales),
                "quantity_per_item": _round_quantity(row.quantity_per_item),
                "unit": row.unit,
            }
        )
    return list(demands.values())


def _entry_numeric_quantity(entry: CountEntry) -> float | None:
    value = getattr(entry, "quantity", None)
    if isinstance(value, int | float):
        return float(value)
    return None


def _stock_name(entry: CountEntry) -> str:
    return str(entry.item_name or entry.item_name_raw or getattr(entry.inventory_item, "name", "") or "").strip()


def _stock_index(count: CountSession) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    for entry in count.entries:
        name = _stock_name(entry)
        key = _canonical_name(name)
        if not key:
            continue
        unit = _canonical_unit(entry.unit)
        quantity = _entry_numeric_quantity(entry)
        bucket = index.setdefault(key, {"name": name, "units": {}, "has_unknown": False})
        if quantity is None:
            bucket["has_unknown"] = True
            continue
        units = bucket["units"]
        assert isinstance(units, dict)
        units[unit] = float(units.get(unit, 0)) + quantity
    return index


def _find_stock_match(demand: IngredientDemand, stock_index: dict[str, dict[str, object]]) -> StockMatch:
    ingredient_key = _canonical_name(demand.ingredient)
    match_key = ingredient_key if ingredient_key in stock_index else ""
    if not match_key:
        ingredient_tokens = set(ingredient_key.split())
        best_score = 0.0
        for stock_key in stock_index:
            stock_tokens = set(stock_key.split())
            if not ingredient_tokens or not stock_tokens:
                continue
            score = len(ingredient_tokens & stock_tokens) / len(ingredient_tokens | stock_tokens)
            if score > best_score and score >= 0.6:
                best_score = score
                match_key = stock_key

    if not match_key:
        return StockMatch(item_name=None, quantity=None, unit=None, status="Stock Unknown")

    match = stock_index[match_key]
    units = match["units"]
    assert isinstance(units, dict)
    item_name = str(match.get("name") or demand.ingredient)
    if demand.unit in units:
        return StockMatch(
            item_name=item_name,
            quantity=_round_quantity(float(units[demand.unit])),
            unit=demand.unit,
            status="Ready",
        )
    if units:
        first_unit, first_quantity = next(iter(units.items()))
        return StockMatch(
            item_name=item_name,
            quantity=_round_quantity(float(first_quantity)),
            unit=str(first_unit),
            status="Unit Mismatch",
        )
    return StockMatch(item_name=item_name, quantity=None, unit=None, status="Stock Unknown")


def _reason_for(demand: IngredientDemand, stock_match: StockMatch, status: str) -> str:
    if len(demand.sources) == 1:
        source = demand.sources[0]
        base = (
            f"Based on {source['weekly_sales']} projected {source['menu_item']} sales "
            f"and {source['quantity_per_item']} {source['unit']} per item."
        )
    else:
        shown = ", ".join(f"{source['menu_item']} ({source['weekly_sales']})" for source in demand.sources[:3])
        remaining = len(demand.sources) - 3
        suffix = f", +{remaining} more" if remaining > 0 else ""
        base = f"Based on projected weekly sales across {shown}{suffix}."
    if status == "Unit Mismatch":
        return f"{base} Current stock is recorded in {stock_match.unit or 'another unit'}, so Koe did not safely subtract it."
    if status == "Stock Unknown":
        return f"{base} No reliable matching current-stock row was found; review before ordering."
    return base


def build_restock_plan(count: CountSession, sales_csv: bytes, recipe_csv: bytes) -> dict:
    sales_rows = parse_sales_csv(sales_csv)
    recipe_rows = parse_recipe_csv(recipe_csv)
    stock_index = _stock_index(count)
    demands = _build_ingredient_demands(sales_rows, recipe_rows)
    rows = []

    for demand in sorted(demands, key=lambda item: item.ingredient.lower()):
        buffered_need = demand.projected_need * (1 + SAFETY_BUFFER_PERCENT / 100)
        stock_match = _find_stock_match(demand, stock_index)
        current_stock = stock_match.quantity if stock_match.status in {"Ready", "Unit Mismatch"} else None
        if stock_match.status == "Ready" and current_stock is not None:
            suggested_purchase = max(buffered_need - current_stock, 0)
            status = "Ready"
        elif stock_match.status == "Unit Mismatch":
            suggested_purchase = buffered_need
            status = "Unit Mismatch"
        else:
            suggested_purchase = buffered_need
            status = "Stock Unknown"

        rows.append(
            {
                "ingredient": demand.ingredient,
                "projected_need": _round_quantity(buffered_need),
                "current_stock": current_stock,
                "current_stock_unit": stock_match.unit,
                "suggested_purchase": _round_quantity(suggested_purchase),
                "unit": demand.unit,
                "status": status,
                "reason": _reason_for(demand, stock_match, status),
            }
        )

    summary = {
        "items_forecasted": len(rows),
        "suggested_purchases": sum(1 for row in rows if float(row["suggested_purchase"] or 0) > 0),
        "needs_review": sum(1 for row in rows if row["status"] != "Ready"),
        "safety_buffer_percent": SAFETY_BUFFER_PERCENT,
    }
    return {"summary": summary, "purchase_plan": rows}
