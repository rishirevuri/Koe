import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    monthly_expected_need: float = 0
    sources: list[dict] = field(default_factory=list)


@dataclass
class StockMatch:
    item_name: str | None
    quantity: float | None
    unit: str | None
    status: str
    reason: str = ""


@dataclass
class HistoryAdjustment:
    multiplier: float | None = None
    raw_multiplier: float | None = None
    history_counts_used: set[int] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    has_problem: bool = False
    is_extreme: bool = False


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
    rounded = round(float(value), 2)
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
        monthly_expected_need = monthly_sales * row.quantity_per_item
        ingredient_key = _canonical_name(row.ingredient_name)
        demand_key = (ingredient_key, row.unit)
        if demand_key not in demands:
            demands[demand_key] = IngredientDemand(ingredient=_display_name(row.ingredient_name), unit=row.unit)
        demand = demands[demand_key]
        demand.projected_need += projected_need
        demand.monthly_expected_need += monthly_expected_need
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


def _entry_has_qualitative_quantity(entry: CountEntry) -> bool:
    label = str(getattr(entry, "quantity_label", "") or "").strip()
    if label:
        return True
    status = str(getattr(entry, "status", "") or "").lower()
    return _entry_numeric_quantity(entry) is None and any(term in status for term in ["review", "estimated", "unknown"])


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
        bucket = index.setdefault(key, {"name": name, "units": {}, "has_unknown": False, "has_qualitative": False})
        if quantity is None:
            bucket["has_unknown"] = True
            if _entry_has_qualitative_quantity(entry):
                bucket["has_qualitative"] = True
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
        return StockMatch(
            item_name=None,
            quantity=None,
            unit=None,
            status="Stock Unknown",
            reason="No matching current stock item was found, so purchase recommendation needs review.",
        )

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
    if match.get("has_qualitative"):
        return StockMatch(
            item_name=item_name,
            quantity=None,
            unit=None,
            status="Needs Review",
            reason="Current stock was counted with a qualitative quantity, so Koe cannot safely subtract it.",
        )
    return StockMatch(
        item_name=item_name,
        quantity=None,
        unit=None,
        status="Needs Review",
        reason="A matching current stock item was found, but its quantity is not numeric.",
    )


def _count_timestamp(count: CountSession):
    return count.completed_at or count.started_at or datetime.min.replace(tzinfo=timezone.utc)


def _count_weight(index: int) -> float:
    return max(0.7, 1 - (index * 0.15))


def _usage_phrase(multiplier: float) -> str:
    delta = multiplier - 1
    percent = round(abs(delta) * 100)
    if percent <= 2:
        return "close to recipe usage"
    direction = "above" if delta > 0 else "below"
    return f"{percent}% {direction} recipe usage"


def _source_phrase(demand: IngredientDemand) -> str:
    if len(demand.sources) == 1:
        source = demand.sources[0]
        return f"{source['weekly_sales']} projected {source['menu_item']} sales and {source['quantity_per_item']} {source['unit']} per item"
    shown = ", ".join(f"{source['menu_item']} ({source['weekly_sales']})" for source in demand.sources[:3])
    remaining = len(demand.sources) - 3
    suffix = f", +{remaining} more" if remaining > 0 else ""
    return f"projected weekly sales across {shown}{suffix}"


def _learn_usage_adjustment(
    demand: IngredientDemand,
    current_match: StockMatch,
    previous_counts: list[CountSession],
) -> HistoryAdjustment:
    adjustment = HistoryAdjustment()
    if not previous_counts or current_match.status != "Ready" or current_match.quantity is None:
        return adjustment
    if demand.monthly_expected_need <= 0:
        return adjustment

    weighted_sum = 0.0
    weight_total = 0.0
    raw_values: list[float] = []
    sorted_counts = sorted(previous_counts, key=_count_timestamp, reverse=True)
    for index, previous_count in enumerate(sorted_counts[:3]):
        previous_match = _find_stock_match(demand, _stock_index(previous_count))
        if previous_match.status != "Ready" or previous_match.quantity is None:
            adjustment.has_problem = True
            adjustment.notes.append(f"{demand.ingredient} history from count #{previous_count.id} could not be used because stock was not numeric in a compatible unit.")
            continue

        observed_depletion = previous_match.quantity - current_match.quantity
        if observed_depletion < 0:
            adjustment.has_problem = True
            adjustment.notes.append(f"{demand.ingredient} increased between count #{previous_count.id} and the current count, so Koe ignored that interval.")
            continue

        raw_multiplier = observed_depletion / demand.monthly_expected_need
        clamped_multiplier = min(2.5, max(0.5, raw_multiplier))
        if clamped_multiplier != raw_multiplier:
            adjustment.is_extreme = True
            adjustment.has_problem = True
            adjustment.notes.append(f"{demand.ingredient} history looked extreme and was clamped for review.")

        weight = _count_weight(index)
        weighted_sum += clamped_multiplier * weight
        weight_total += weight
        raw_values.append(raw_multiplier)
        adjustment.history_counts_used.add(previous_count.id)

    if weight_total:
        adjustment.multiplier = weighted_sum / weight_total
        adjustment.raw_multiplier = sum(raw_values) / len(raw_values) if raw_values else None
        adjustment.notes.insert(0, f"{demand.ingredient} usually runs {_usage_phrase(adjustment.multiplier)}.")
    return adjustment


def _reason_for(
    demand: IngredientDemand,
    stock_match: StockMatch,
    status: str,
    *,
    history: HistoryAdjustment,
    adjusted_need: float,
) -> str:
    source = _source_phrase(demand)
    projected = _round_quantity(demand.projected_need)
    adjusted = _round_quantity(adjusted_need)
    if status == "Unit Mismatch":
        return f"Recipe uses {demand.unit} but current stock is counted in {stock_match.unit or 'another unit'}, so Koe cannot safely subtract stock."
    if status == "Stock Unknown":
        return "No matching current stock item was found, so purchase recommendation needs review."
    if status == "Needs Review" and stock_match.status == "Needs Review":
        return stock_match.reason or "Current stock needs review before Koe can safely subtract it."
    if history.multiplier is not None:
        stock = f" Current stock is {_round_quantity(stock_match.quantity or 0)} {stock_match.unit or demand.unit}."
        qualifier = " Historical usage looked extreme and should be reviewed." if history.is_extreme else ""
        return f"Sales and recipes projected {projected} {demand.unit}. Past counts show this item usually runs {_usage_phrase(history.multiplier)}. Adjusted need is {adjusted} {demand.unit}.{stock}{qualifier}"
    if status == "Needs Review":
        return "Count history had unusual movement, so Koe used recipe demand only and flagged this row for manager review."
    return f"Based on sales and recipe usage only from {source}. Add previous counts to learn actual depletion."


def build_restock_plan(
    count: CountSession,
    sales_csv: bytes,
    recipe_csv: bytes,
    previous_counts: list[CountSession] | None = None,
) -> dict:
    sales_rows = parse_sales_csv(sales_csv)
    recipe_rows = parse_recipe_csv(recipe_csv)
    previous_counts = previous_counts or []
    stock_index = _stock_index(count)
    demands = _build_ingredient_demands(sales_rows, recipe_rows)
    rows = []
    learning_notes: list[dict[str, str]] = []
    history_counts_used: set[int] = set()

    for demand in sorted(demands, key=lambda item: item.ingredient.lower()):
        stock_match = _find_stock_match(demand, stock_index)
        history = _learn_usage_adjustment(demand, stock_match, previous_counts)
        if history.history_counts_used:
            history_counts_used.update(history.history_counts_used)
        if history.notes:
            learning_notes.extend({"ingredient": demand.ingredient, "note": note} for note in history.notes)

        adjusted_need = demand.projected_need * (history.multiplier if history.multiplier is not None else 1)
        buffered_need = adjusted_need * (1 + SAFETY_BUFFER_PERCENT / 100)
        current_stock = stock_match.quantity if stock_match.status in {"Ready", "Unit Mismatch"} else None
        if stock_match.status == "Ready" and current_stock is not None:
            suggested_purchase = max(buffered_need - current_stock, 0)
            if history.multiplier is not None:
                status = "Needs Review" if history.is_extreme else "Ready"
            elif history.has_problem:
                status = "Needs Review"
            else:
                status = "Limited History"
        elif stock_match.status == "Unit Mismatch":
            suggested_purchase = buffered_need
            status = "Unit Mismatch"
        elif stock_match.status == "Needs Review":
            suggested_purchase = buffered_need
            status = "Needs Review"
        else:
            suggested_purchase = buffered_need
            status = "Stock Unknown"

        rows.append(
            {
                "ingredient": demand.ingredient,
                "projected_need": _round_quantity(demand.projected_need),
                "adjusted_need": _round_quantity(adjusted_need),
                "current_stock": current_stock,
                "current_stock_unit": stock_match.unit,
                "suggested_purchase": _round_quantity(suggested_purchase),
                "unit": demand.unit,
                "usage_multiplier": _round_quantity(history.multiplier) if history.multiplier is not None else None,
                "status": status,
                "reason": _reason_for(demand, stock_match, status, history=history, adjusted_need=adjusted_need),
            }
        )

    forecast_mode = "adaptive" if history_counts_used else "limited_history" if previous_counts else "recipe_only"
    summary = {
        "items_forecasted": len(rows),
        "suggested_purchases": sum(1 for row in rows if float(row["suggested_purchase"] or 0) > 0),
        "needs_review": sum(1 for row in rows if row["status"] in {"Needs Review", "Unit Mismatch", "Stock Unknown"}),
        "safety_buffer_percent": SAFETY_BUFFER_PERCENT,
        "history_counts_used": len(history_counts_used),
        "forecast_mode": forecast_mode,
    }
    return {"summary": summary, "purchase_plan": rows, "learning_notes": learning_notes}
