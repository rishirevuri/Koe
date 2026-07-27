import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import CountEntry, CountSession
from app.services.external_ai_service import generate_restock_plan_with_claude, normalize_sales_report_with_claude
from app.utils.text import normalize_text, simple_singular
from app.utils.units import normalize_unit


SAFETY_BUFFER_PERCENT = 10
MAX_CSV_BYTES = 2 * 1024 * 1024
RESTOCK_REVIEW_STATUSES = {"Needs Review", "Unit Mismatch", "Stock Unknown"}
ALLOWED_ACTIONS = {"buy", "hold", "review"}
ALLOWED_RESTOCK_STATUSES = {"Ready", "Limited History", "Stock Unknown", "Unit Mismatch", "Needs Review"}
ALLOWED_CONFIDENCE = {"High", "Medium", "Low"}
ALLOWED_USAGE_SIGNALS = {"low", "medium", "high", "unknown"}
ALLOWED_HISTORY_SIGNALS = {
    "stable",
    "depletes_faster_than_expected",
    "depletes_slower_than_expected",
    "inconsistent",
    "limited_history",
    "unknown",
}
ALLOWED_RISK_SIGNALS = {"stockout_risk", "waste_risk", "balanced", "needs_review"}
SALES_NORMALIZATION_ERROR = "Koe could not read sales quantities from this file. Try another export or paste the report text."
SALES_CONFIDENCE_ORDER = {"Low": 0, "Medium": 1, "High": 2}
SALES_ITEM_COLUMN_ALIASES = {
    "itemname",
    "item",
    "menuitem",
    "product",
    "productname",
    "name",
    "description",
    "solditem",
}
SALES_QUANTITY_COLUMN_ALIASES = {
    "quantitysold",
    "qty",
    "quantity",
    "qtysold",
    "itemssold",
    "unitssold",
    "count",
    "netqty",
    "sold",
}
SALES_DATE_COLUMN_ALIASES = {"date", "businessdate", "orderdate", "transactiondate", "saledate"}
SALES_SUMMARY_TERMS = {
    "subtotal",
    "grandtotal",
    "total",
    "tax",
    "tip",
    "tips",
    "discount",
    "discounts",
    "refund",
    "refunds",
    "payment",
    "paymentmethod",
    "cash",
    "visa",
    "mastercard",
    "amex",
}


class RestockPlannerError(ValueError):
    pass


class ClaudeRestockValidationError(ValueError):
    pass


@dataclass
class SalesRow:
    item_name: str
    quantity_sold: float
    date: str | None = None
    confidence: str = "High"
    source_hint: str = ""


@dataclass
class SalesNormalizationResult:
    rows: list[SalesRow]
    source: str
    rows_read: int
    columns_detected: dict[str, str | None]
    warnings: list[dict[str, str]] = field(default_factory=list)

    def to_response(self) -> dict:
        return {
            "source": self.source,
            "rows_read": self.rows_read,
            "sales_rows_extracted": len(self.rows),
            "columns_detected": self.columns_detected,
            "warnings": self.warnings,
            "preview_rows": [
                {
                    "item_name": row.item_name,
                    "quantity_sold": _round_quantity(row.quantity_sold),
                    "date": row.date,
                    "confidence": row.confidence,
                    "source_hint": row.source_hint,
                }
                for row in self.rows[:5]
            ],
        }


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


def _decode_csv_text(data: bytes, *, label: str) -> str:
    if not data:
        raise RestockPlannerError(f"{label} CSV is empty.")
    if len(data) > MAX_CSV_BYTES:
        raise RestockPlannerError(f"{label} CSV is too large. Upload a file under 2 MB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RestockPlannerError(f"{label} CSV must be UTF-8 text.") from exc


def _read_csv_rows(data: bytes, *, label: str, required_columns: list[str]) -> list[dict[str, str]]:
    text = _decode_csv_text(data, label=label)
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


def _detect_sales_columns(fieldnames: list[str] | None) -> dict[str, str | None]:
    detected: dict[str, str | None] = {"item_name": None, "quantity_sold": None, "date": None}
    for header in fieldnames or []:
        key = _header_key(header)
        if not detected["item_name"] and key in SALES_ITEM_COLUMN_ALIASES:
            detected["item_name"] = header
        if not detected["quantity_sold"] and key in SALES_QUANTITY_COLUMN_ALIASES:
            detected["quantity_sold"] = header
        if not detected["date"] and key in SALES_DATE_COLUMN_ALIASES:
            detected["date"] = header
    return detected


def _is_summary_sales_item(item_name: str) -> bool:
    key = _header_key(item_name)
    normalized = normalize_text(item_name)
    if not key:
        return True
    if key in SALES_SUMMARY_TERMS:
        return True
    return any(term in normalized.split() for term in SALES_SUMMARY_TERMS)


def _confidence_floor(current: str, next_value: str) -> str:
    current = current if current in SALES_CONFIDENCE_ORDER else "Medium"
    next_value = next_value if next_value in SALES_CONFIDENCE_ORDER else "Medium"
    return current if SALES_CONFIDENCE_ORDER[current] <= SALES_CONFIDENCE_ORDER[next_value] else next_value


def _merge_sales_rows(rows: list[SalesRow]) -> list[SalesRow]:
    merged: dict[str, SalesRow] = {}
    for row in rows:
        key = _canonical_name(row.item_name)
        if key not in merged:
            merged[key] = SalesRow(
                item_name=_display_name(row.item_name),
                quantity_sold=float(row.quantity_sold),
                date=row.date,
                confidence=row.confidence,
                source_hint=row.source_hint,
            )
            continue
        existing = merged[key]
        existing.quantity_sold += float(row.quantity_sold)
        existing.date = existing.date if existing.date == row.date else None
        existing.confidence = _confidence_floor(existing.confidence, row.confidence)
    return sorted(merged.values(), key=lambda row: row.item_name.lower())


def _parse_sales_text_direct(text: str) -> SalesNormalizationResult:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RestockPlannerError("Sales CSV is missing a header row.")
    detected = _detect_sales_columns(reader.fieldnames)
    if not detected["item_name"] or not detected["quantity_sold"]:
        raise RestockPlannerError("Sales CSV did not contain recognizable sales columns.")

    rows: list[SalesRow] = []
    warnings: list[dict[str, str]] = []
    rows_read = 0
    ignored_rows = 0
    for index, raw_row in enumerate(reader, start=2):
        rows_read += 1
        item_name = str(raw_row.get(detected["item_name"] or "") or "").strip()
        if not item_name or _is_summary_sales_item(item_name):
            ignored_rows += 1
            continue
        try:
            quantity_sold = _parse_float(
                raw_row.get(detected["quantity_sold"] or ""),
                field_name="quantity_sold",
                row_number=index,
                label="Sales",
            )
        except RestockPlannerError:
            ignored_rows += 1
            continue
        if quantity_sold < 0:
            ignored_rows += 1
            continue
        if quantity_sold == 0:
            ignored_rows += 1
            continue
        rows.append(
            SalesRow(
                item_name=item_name,
                quantity_sold=quantity_sold,
                date=str(raw_row.get(detected["date"] or "") or "").strip() or None,
                confidence="High",
                source_hint=f"Matched from {detected['item_name']} and {detected['quantity_sold']} columns",
            )
        )

    merged = _merge_sales_rows(rows)
    if ignored_rows:
        warnings.append({"message": f"Koe ignored {ignored_rows} summary, blank, or non-sales rows while cleaning this report."})
    if not merged:
        raise RestockPlannerError(SALES_NORMALIZATION_ERROR)
    return SalesNormalizationResult(
        rows=merged,
        source="direct",
        rows_read=rows_read,
        columns_detected=detected,
        warnings=warnings,
    )


def _validate_claude_sales_payload(payload: dict, *, rows_read: int) -> SalesNormalizationResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("sales_rows"), list):
        raise RestockPlannerError(SALES_NORMALIZATION_ERROR)

    parsed_rows: list[SalesRow] = []
    for raw_row in payload["sales_rows"]:
        if not isinstance(raw_row, dict):
            continue
        item_name = _display_name(str(raw_row.get("item_name") or ""))
        if not item_name or item_name == "Unnamed ingredient":
            continue
        quantity = raw_row.get("quantity_sold")
        try:
            quantity_sold = float(str(quantity).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if quantity_sold <= 0:
            continue
        confidence = str(raw_row.get("confidence") or "Medium").strip()
        if confidence not in SALES_CONFIDENCE_ORDER:
            confidence = "Medium"
        parsed_rows.append(
            SalesRow(
                item_name=item_name,
                quantity_sold=quantity_sold,
                date=str(raw_row.get("date") or "").strip() or None,
                confidence=confidence,
                source_hint=str(raw_row.get("source_hint") or "").strip(),
            )
        )

    merged = _merge_sales_rows(parsed_rows)
    if not merged:
        raise RestockPlannerError(SALES_NORMALIZATION_ERROR)

    raw_summary = payload.get("normalization_summary") if isinstance(payload.get("normalization_summary"), dict) else {}
    raw_columns = raw_summary.get("columns_detected") if isinstance(raw_summary.get("columns_detected"), dict) else {}
    warnings = []
    for warning in payload.get("warnings") or []:
        if isinstance(warning, dict) and str(warning.get("message") or "").strip():
            warnings.append({"message": str(warning["message"]).strip()})

    return SalesNormalizationResult(
        rows=merged,
        source="claude",
        rows_read=int(raw_summary.get("rows_read") or rows_read),
        columns_detected={
            "item_name": str(raw_columns.get("item_name") or "") or None,
            "quantity_sold": str(raw_columns.get("quantity_sold") or "") or None,
            "date": str(raw_columns.get("date") or "") or None,
        },
        warnings=warnings,
    )


def normalize_sales_csv(data: bytes, *, use_claude: bool = False) -> SalesNormalizationResult:
    text = _decode_csv_text(data, label="Sales")
    lines = [line for line in text.splitlines() if line.strip()]
    rows_read = max(0, len(lines) - 1)
    try:
        return _parse_sales_text_direct(text)
    except RestockPlannerError as direct_error:
        if not use_claude:
            if str(direct_error) == SALES_NORMALIZATION_ERROR:
                raise
            raise RestockPlannerError(SALES_NORMALIZATION_ERROR) from direct_error

    try:
        payload = normalize_sales_report_with_claude(text)
        return _validate_claude_sales_payload(payload, rows_read=rows_read)
    except Exception as exc:
        raise RestockPlannerError(SALES_NORMALIZATION_ERROR) from exc


def parse_sales_csv(data: bytes) -> list[SalesRow]:
    return normalize_sales_csv(data, use_claude=False).rows


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
                "quantity_sold": _round_quantity(monthly_sales),
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


def _perishability_context(ingredient: str) -> dict[str, str]:
    name = _canonical_name(ingredient)

    def has_any(*terms: str) -> bool:
        return any(term in name for term in terms)

    if has_any("lettuce", "tomato", "romaine", "cucumber", "cilantro", "basil", "berry", "avocado", "lemon", "lime"):
        return {"category": "Produce", "perishability": "high", "stockout_risk": "medium", "waste_risk": "high"}
    if has_any("chicken", "beef", "bacon", "turkey", "salmon", "egg"):
        return {"category": "Proteins", "perishability": "medium/high", "stockout_risk": "high", "waste_risk": "medium"}
    if has_any("milk", "cream", "cheese", "butter", "yogurt"):
        return {"category": "Dairy", "perishability": "medium/high", "stockout_risk": "medium/high", "waste_risk": "medium/high"}
    if has_any("rice", "flour", "sugar", "pasta", "bean"):
        return {"category": "Dry Goods", "perishability": "low", "stockout_risk": "medium", "waste_risk": "low"}
    if has_any("mayo", "ketchup", "mustard", "ranch", "caesar", "pesto", "marinara", "tomato sauce", "pickle"):
        return {"category": "Sauces/Condiments", "perishability": "medium", "stockout_risk": "medium", "waste_risk": "medium"}
    if has_any("cup", "lid", "straw", "napkin", "fork", "spoon", "box", "bowl", "wrap", "container"):
        return {"category": "Packaging/Supplies", "perishability": "low", "stockout_risk": "high", "waste_risk": "low"}
    if has_any("frozen", "fries", "mozzarella stick", "ice cream"):
        return {"category": "Frozen", "perishability": "medium", "stockout_risk": "medium", "waste_risk": "medium"}
    return {"category": "Uncategorized", "perishability": "unknown", "stockout_risk": "unknown", "waste_risk": "unknown"}


def _stock_quality(stock_match: StockMatch) -> str:
    if stock_match.status == "Ready":
        return "numeric"
    if stock_match.status == "Unit Mismatch":
        return "numeric_in_incompatible_unit"
    if stock_match.status == "Stock Unknown":
        return "unknown"
    return "qualitative_or_unclear"


def _unit_quality(stock_match: StockMatch) -> str:
    if stock_match.status == "Ready":
        return "compatible"
    if stock_match.status == "Unit Mismatch":
        return "incompatible"
    if stock_match.status == "Stock Unknown":
        return "unknown"
    return "needs_review"


def _usage_signal(history: HistoryAdjustment | None) -> str:
    multiplier = history.multiplier if history else None
    if multiplier is None:
        return "unknown"
    if multiplier >= 1.15:
        return "high"
    if multiplier <= 0.85:
        return "low"
    return "medium"


def _history_signal(history: HistoryAdjustment | None, previous_counts: list[CountSession]) -> str:
    if not previous_counts:
        return "limited_history"
    if not history or history.multiplier is None:
        return "inconsistent" if history and history.has_problem else "limited_history"
    if history.is_extreme or history.has_problem:
        return "inconsistent"
    if history.multiplier >= 1.1:
        return "depletes_faster_than_expected"
    if history.multiplier <= 0.9:
        return "depletes_slower_than_expected"
    return "stable"


def _risk_signal(status: str, suggested_purchase: float, context: dict[str, str]) -> str:
    if status in RESTOCK_REVIEW_STATUSES:
        return "needs_review"
    if suggested_purchase <= 0:
        return "balanced"
    if context.get("waste_risk") == "high" and context.get("stockout_risk") != "high":
        return "waste_risk"
    if context.get("stockout_risk") in {"high", "medium/high"}:
        return "stockout_risk"
    return "balanced"


def _deterministic_action(status: str, suggested_purchase: float) -> str:
    if status in RESTOCK_REVIEW_STATUSES:
        return "review"
    if suggested_purchase <= 0:
        return "hold"
    return "buy"


def _deterministic_confidence(status: str, history: HistoryAdjustment | None) -> str:
    if status in {"Stock Unknown", "Unit Mismatch", "Needs Review"}:
        return "Low"
    if history and history.multiplier is not None and not history.has_problem:
        return "High"
    return "Medium"


def _current_stock_evidence(stock_match: StockMatch) -> dict:
    return {
        "matched_item_name": stock_match.item_name,
        "quantity": stock_match.quantity,
        "unit": stock_match.unit,
        "status": stock_match.status,
        "is_numeric": stock_match.quantity is not None,
        "reason": stock_match.reason,
    }


def _previous_count_evidence(demand: IngredientDemand, previous_counts: list[CountSession]) -> list[dict]:
    rows: list[dict] = []
    for previous_count in sorted(previous_counts, key=_count_timestamp, reverse=True)[:3]:
        previous_match = _find_stock_match(demand, _stock_index(previous_count))
        rows.append(
            {
                "count_id": previous_count.id,
                "count_date": _count_timestamp(previous_count).isoformat(),
                "matched_item_name": previous_match.item_name,
                "quantity": previous_match.quantity,
                "unit": previous_match.unit,
                "status": previous_match.status,
                "is_numeric": previous_match.quantity is not None,
            }
        )
    return rows


def _evidence_for_ingredient(
    demand: IngredientDemand,
    stock_match: StockMatch,
    previous_counts: list[CountSession],
    history: HistoryAdjustment,
    *,
    deterministic_adjusted_need: float,
    deterministic_suggested_purchase: float,
) -> dict:
    return {
        "ingredient_name": demand.ingredient,
        "recipe_unit": demand.unit,
        "menu_usage": [
            {
                "menu_item": source["menu_item"],
                "quantity_sold": source.get("quantity_sold", 0),
                "weekly_sales": source.get("weekly_sales", 0),
                "quantity_per_item": source["quantity_per_item"],
                "unit": source["unit"],
            }
            for source in demand.sources
        ],
        "current_stock": _current_stock_evidence(stock_match),
        "previous_counts": _previous_count_evidence(demand, previous_counts),
        "deterministic_signals": {
            "recipe_projected_need": _round_quantity(demand.projected_need),
            "monthly_expected_need": _round_quantity(demand.monthly_expected_need),
            "deterministic_adjusted_need": _round_quantity(deterministic_adjusted_need),
            "deterministic_suggested_purchase": _round_quantity(deterministic_suggested_purchase),
            "usage_multiplier": _round_quantity(history.multiplier) if history.multiplier is not None else None,
            "has_usable_history": bool(history.history_counts_used),
            "unit_quality": _unit_quality(stock_match),
            "stock_quality": _stock_quality(stock_match),
            "history_signal": _history_signal(history, previous_counts),
        },
        "category_context": _perishability_context(demand.ingredient),
    }


def _safe_float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ClaudeRestockValidationError("Claude returned a non-numeric quantity field") from exc
    return _round_quantity(parsed)


def _safe_current_stock(value: object) -> float | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return _round_quantity(float(value))
    return str(value).strip() or None


def _safe_choice(value: object, allowed: set[str], *, field_name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ClaudeRestockValidationError(f"Claude returned invalid {field_name}")
    return text


def _fallback_reason(error: Exception) -> str:
    message = str(error)
    if message == "External AI integrations are disabled":
        return "external_ai_disabled"
    if message == "Text AI provider is not Claude":
        return "text_ai_provider_not_claude"
    if message == "Claude is not configured":
        return "claude_not_configured"
    prefix = "claude_validation_failed" if isinstance(error, ClaudeRestockValidationError) else f"claude_error:{type(error).__name__}"
    safe_message = " ".join(message.split())[:180]
    return f"{prefix}:{safe_message}" if safe_message else prefix


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


def _build_deterministic_plan_context(
    count: CountSession,
    sales_csv: bytes,
    recipe_csv: bytes,
    previous_counts: list[CountSession] | None = None,
    *,
    use_claude: bool = False,
) -> dict:
    sales_normalization = normalize_sales_csv(sales_csv, use_claude=use_claude)
    sales_rows = sales_normalization.rows
    recipe_rows = parse_recipe_csv(recipe_csv)
    previous_counts = previous_counts or []
    stock_index = _stock_index(count)
    demands = _build_ingredient_demands(sales_rows, recipe_rows)
    rows = []
    evidence_rows = []
    learning_notes: list[dict[str, str]] = []
    review_warnings: list[dict[str, str]] = []
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

        context = _perishability_context(demand.ingredient)
        suggested_purchase = _round_quantity(suggested_purchase)
        adjusted_need = _round_quantity(adjusted_need)
        action = _deterministic_action(status, float(suggested_purchase or 0))
        risk_signal = _risk_signal(status, float(suggested_purchase or 0), context)
        if status in RESTOCK_REVIEW_STATUSES:
            review_warnings.append(
                {
                    "ingredient": demand.ingredient,
                    "warning": _reason_for(demand, stock_match, status, history=history, adjusted_need=float(adjusted_need or 0)),
                }
            )

        rows.append(
            {
                "ingredient": demand.ingredient,
                "projected_need": _round_quantity(demand.projected_need),
                "adjusted_need": adjusted_need,
                "current_stock": current_stock,
                "current_stock_unit": stock_match.unit,
                "suggested_purchase": suggested_purchase,
                "unit": demand.unit,
                "usage_multiplier": _round_quantity(history.multiplier) if history.multiplier is not None else None,
                "action": action,
                "status": status,
                "confidence": _deterministic_confidence(status, history),
                "usage_signal": _usage_signal(history),
                "history_signal": _history_signal(history, previous_counts),
                "risk_signal": risk_signal,
                "reason": _reason_for(demand, stock_match, status, history=history, adjusted_need=adjusted_need),
            }
        )
        evidence_rows.append(
            _evidence_for_ingredient(
                demand,
                stock_match,
                previous_counts,
                history,
                deterministic_adjusted_need=float(adjusted_need or 0),
                deterministic_suggested_purchase=float(suggested_purchase or 0),
            )
        )

    forecast_mode = "deterministic_adaptive" if history_counts_used else "deterministic_recipe_only"
    summary = {
        "items_forecasted": len(rows),
        "suggested_purchases": sum(1 for row in rows if float(row["suggested_purchase"] or 0) > 0),
        "needs_review": sum(1 for row in rows if row["status"] in {"Needs Review", "Unit Mismatch", "Stock Unknown"}),
        "safety_buffer_percent": SAFETY_BUFFER_PERCENT,
        "history_counts_used": len(history_counts_used),
        "forecast_mode": forecast_mode,
        "planner_source": "deterministic_fallback",
        "fallback_reason": None,
    }
    evidence_packet = {
        "safety_buffer_percent": SAFETY_BUFFER_PERCENT,
        "forecast_period": "next_week",
        "current_count_id": count.id,
        "current_count_date": _count_timestamp(count).isoformat(),
        "previous_count_ids": [previous_count.id for previous_count in previous_counts],
        "sales_normalization": sales_normalization.to_response(),
        "ingredients": evidence_rows,
    }
    return {
        "plan": {
            "summary": summary,
            "purchase_plan": rows,
            "learning_notes": learning_notes,
            "review_warnings": review_warnings,
            "sales_normalization": sales_normalization.to_response(),
        },
        "evidence_packet": evidence_packet,
        "sales_normalization": sales_normalization,
        "history_counts_used": history_counts_used,
    }


def _sanitize_claude_notes(raw_notes: object, evidence_keys: set[str], *, field_name: str) -> list[dict[str, str]]:
    if not isinstance(raw_notes, list):
        return []
    sanitized: list[dict[str, str]] = []
    for raw_note in raw_notes:
        if not isinstance(raw_note, dict):
            continue
        ingredient = _display_name(str(raw_note.get("ingredient") or "Inventory"))
        message = str(raw_note.get("note" if field_name == "note" else "warning") or "").strip()
        if not message:
            continue
        if ingredient != "Inventory" and _canonical_name(ingredient) not in evidence_keys:
            continue
        sanitized.append({"ingredient": ingredient, field_name: message})
    return sanitized


def _validate_claude_plan(claude_payload: dict, deterministic_context: dict) -> dict:
    evidence_packet = deterministic_context["evidence_packet"]
    ingredients = evidence_packet.get("ingredients") or []
    evidence_by_key = {_canonical_name(ingredient["ingredient_name"]): ingredient for ingredient in ingredients}
    evidence_keys = set(evidence_by_key)
    if not isinstance(claude_payload, dict):
        raise ClaudeRestockValidationError("Claude response must be a JSON object")
    raw_rows = claude_payload.get("purchase_plan")
    if not isinstance(raw_rows, list):
        raise ClaudeRestockValidationError("Claude purchase_plan must be a list")

    rows: list[dict] = []
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        ingredient = _display_name(str(raw_row.get("ingredient") or ""))
        ingredient_key = _canonical_name(ingredient)
        if ingredient_key not in evidence_by_key:
            warnings.append(
                {
                    "ingredient": "Inventory",
                    "warning": f"Claude returned an ingredient outside the evidence packet: {ingredient or 'unnamed item'}. Koe dropped it.",
                }
            )
            continue
        if ingredient_key in seen:
            warnings.append({"ingredient": ingredient, "warning": "Claude returned a duplicate row for this ingredient. Koe kept the first one."})
            continue

        reason = str(raw_row.get("reason") or "").strip()
        if not reason:
            raise ClaudeRestockValidationError("Claude row is missing a reason")

        status = _safe_choice(raw_row.get("status"), ALLOWED_RESTOCK_STATUSES, field_name="status")
        action = _safe_choice(raw_row.get("action"), ALLOWED_ACTIONS, field_name="action")
        confidence = _safe_choice(raw_row.get("confidence"), ALLOWED_CONFIDENCE, field_name="confidence")
        usage_signal = _safe_choice(raw_row.get("usage_signal", "unknown"), ALLOWED_USAGE_SIGNALS, field_name="usage_signal")
        history_signal = _safe_choice(raw_row.get("history_signal", "unknown"), ALLOWED_HISTORY_SIGNALS, field_name="history_signal")
        risk_signal = _safe_choice(raw_row.get("risk_signal", "needs_review"), ALLOWED_RISK_SIGNALS, field_name="risk_signal")

        suggested_purchase = _safe_float_or_none(raw_row.get("suggested_purchase"))
        if suggested_purchase is not None and suggested_purchase < 0:
            suggested_purchase = 0
            warnings.append({"ingredient": ingredient, "warning": "Claude returned a negative purchase quantity. Koe repaired it to zero."})
        if action == "hold":
            suggested_purchase = 0 if suggested_purchase is not None else None
        if status == "Stock Unknown":
            confidence = "Low"
        if status == "Unit Mismatch" and suggested_purchase is not None and "estimate" not in reason.lower():
            suggested_purchase = None
            action = "review"
            confidence = "Low"
            warnings.append({"ingredient": ingredient, "warning": "Units did not match, so Koe removed the purchase quantity for manager review."})

        evidence = evidence_by_key[ingredient_key]
        rows.append(
            {
                "ingredient": evidence["ingredient_name"],
                "projected_need": _safe_float_or_none(raw_row.get("projected_need")),
                "adjusted_need": _safe_float_or_none(raw_row.get("adjusted_need")),
                "current_stock": _safe_current_stock(raw_row.get("current_stock")),
                "current_stock_unit": evidence.get("current_stock", {}).get("unit"),
                "suggested_purchase": suggested_purchase,
                "unit": raw_row.get("unit") or evidence.get("recipe_unit"),
                "usage_multiplier": evidence.get("deterministic_signals", {}).get("usage_multiplier"),
                "action": action,
                "status": status,
                "confidence": confidence,
                "usage_signal": usage_signal,
                "history_signal": history_signal,
                "risk_signal": risk_signal,
                "reason": reason,
            }
        )
        seen.add(ingredient_key)

    if ingredients and not rows:
        raise ClaudeRestockValidationError("Claude returned no usable purchase rows")

    raw_summary = claude_payload.get("summary") if isinstance(claude_payload.get("summary"), dict) else {}
    raw_forecast_mode = str(raw_summary.get("forecast_mode") or "").strip()
    history_counts_used = len(deterministic_context["history_counts_used"])
    forecast_mode = raw_forecast_mode if raw_forecast_mode in {"claude_adaptive", "claude_recipe_only"} else ""
    if not forecast_mode:
        forecast_mode = "claude_adaptive" if history_counts_used else "claude_recipe_only"

    review_warnings = _sanitize_claude_notes(claude_payload.get("review_warnings"), evidence_keys, field_name="warning")
    review_warnings.extend(warnings)
    summary = {
        "items_forecasted": len(rows),
        "suggested_purchases": sum(1 for row in rows if row["action"] == "buy" and float(row["suggested_purchase"] or 0) > 0),
        "needs_review": sum(1 for row in rows if row["status"] in RESTOCK_REVIEW_STATUSES or row["action"] == "review"),
        "safety_buffer_percent": SAFETY_BUFFER_PERCENT,
        "history_counts_used": history_counts_used,
        "forecast_mode": forecast_mode,
        "planner_source": "claude",
        "fallback_reason": None,
        "overall_note": str(raw_summary.get("overall_note") or "").strip() or None,
    }
    return {
        "summary": summary,
        "purchase_plan": rows,
        "learning_notes": _sanitize_claude_notes(claude_payload.get("learning_notes"), evidence_keys, field_name="note"),
        "review_warnings": review_warnings,
        "sales_normalization": deterministic_context["sales_normalization"].to_response(),
    }


def build_restock_plan(
    count: CountSession,
    sales_csv: bytes,
    recipe_csv: bytes,
    previous_counts: list[CountSession] | None = None,
    *,
    use_claude: bool = False,
) -> dict:
    context = _build_deterministic_plan_context(count, sales_csv, recipe_csv, previous_counts, use_claude=use_claude)
    deterministic_plan = context["plan"]
    if not use_claude:
        return deterministic_plan

    try:
        claude_payload = generate_restock_plan_with_claude(context["evidence_packet"])
        return _validate_claude_plan(claude_payload, context)
    except Exception as exc:
        deterministic_plan["summary"]["fallback_reason"] = _fallback_reason(exc)
        deterministic_plan["summary"]["planner_source"] = "deterministic_fallback"
        return deterministic_plan
