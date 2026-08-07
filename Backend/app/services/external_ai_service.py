import json
import logging
import re

import httpx

from app.config import get_settings
from app.services.category_service import normalize_inventory_category
from app.services.voice_parse_service import ParsedCandidate, _container_unit, _normalize_fullness, normalize_obvious_item_unit
from app.utils.units import normalize_unit


logger = logging.getLogger(__name__)


def disabled_response(provider: str, message: str) -> dict[str, bool | str]:
    return {"configured": False, "provider": provider, "message": message}


RESTAURANT_INVENTORY_SYSTEM_PROMPT = """
You are Koe, an expert restaurant inventory data-cleaning engine.

Your task is to convert one messy spoken restaurant inventory transcript into clean structured inventory rows.

You are not a chatbot. You are not writing prose. You return valid JSON only.

You must parse the full transcript globally, not phrase-by-phrase. Use context from the entire transcript to handle corrections, duplicates, package sizes, spoiled items, vague quantities, and partial containers.

Core rules:

1. Extract real inventory items only.
Do not create rows from filler words, connectors, or partial grammar.

Never create item names like:
- "of"
- "and"
- "but"
- "then"
- "packs of"
- "cases of"
- "bunches wait"
- "is half empty"
- "there are"
- "regular tomatoes, but"
- "are soft and starting to rot"
- "cilantro. There are"
- "lemons with"
- "in the case, but"
- "lemons are bad"
- "I have"
- "with"
- "actually change that to"

If a phrase does not contain a real item, ignore it.

2. Clean item names.
item_name_clean must be the real product name only.

Good:
- "Whole milk"
- "2 percent milk"
- "Heavy cream"
- "Olive oil"
- "Tomato sauce"
- "Roma tomatoes"
- "Water bottles"
- "Chicken breasts"
- "Ground beef"

Bad:
- "percent milk. There is half a gallon of heavy cream"
- "olive oil and one of the bottles is half empty"
- "cans of tomato sauce, actually change that to"
- "dozen eggs, but"

3. Preserve raw/source phrase separately.
Use original_phrase for the relevant source text, but do not put sentence fragments into item_name_clean.

4. Handle corrections.
If the speaker corrects themselves, use the final corrected value.

Examples:
- "10 tomatoes, actually make that 12 tomatoes" -> Tomatoes, quantity 12
- "3 bunches, wait no scratch that, 4 bunches of cilantro" -> Cilantro, quantity 4
- "6 cans of tomato sauce, actually change that to 8 cans" -> Tomato sauce, quantity 8
- "not olive oil, canola oil" -> Canola oil

Do not create separate rows for the discarded quantity.

5. Handle package conversions.
Convert package/count units only when the transcript gives a clear conversion.

Rules:
- 1 dozen = 12
- half dozen = 6
- 1 gross = 144
- N trays of M items = N x M items
- N packs of M items = N x M items
- N cases of M items = N x M items
- N ten-pound bags = N x 10 pounds
- N five-pound bags = N x 5 pounds

Examples:
- "10 dozen eggs" -> 120 eggs
- "12 dozen eggs" -> 144 eggs
- "2 trays of 30 eggs" -> 60 eggs
- "2 cases of 24 water bottles" -> 48 bottles
- "3 packs of 6 Coke cans" -> 18 cans
- "4 five-pound bags of chicken wings" -> 20 pounds
- "2 ten-pound bags of rice" -> 20 pounds

6. Handle spoiled/broken/unusable items.
If the user says some items are spoiled, cracked, broken, unusable, or should not be counted, subtract them from the usable quantity when the item is the same.

Example:
"12 dozen eggs, but 6 eggs are cracked so do not count those as usable. There are also 2 trays of 30 eggs."
12 dozen eggs = 144
minus 6 cracked = 138
plus 60 backup eggs = 198 usable eggs
Final row:
Eggs, quantity 198, unit eggs, status Converted Unit

7. Handle partial containers.
Convert clear partials.

Examples:
- "3 bottles of olive oil and one is half empty" -> 2.5 bottles
- "5 bags of flour, one bag is half empty" -> 4.5 bags
- "half a case of napkins" -> 0.5 cases
- "quarter bag of sugar" -> 0.25 bags
- "3 tubs of ice cream, one tub is only a quarter full" -> 2.25 tubs
- "half a box of veggie patties" -> 0.5 boxes

If the partial amount is vague, mark Needs Review.

8. Handle vague quantities.
If quantity is vague, set quantity to null and status Needs Review.

Examples:
- "a few limes" -> Limes, quantity null, unit null or individual, status Needs Review
- "some tomatoes" -> Tomatoes, quantity null, status Needs Review
- "boxes of bacon, not sure how many" -> Bacon, quantity null, unit boxes, Needs Review
- If later corrected, use the correction:
  "boxes of bacon, not sure how many, actually 2 boxes" -> Bacon, 2 boxes, Clean

9. Extract explicitly stated needed quantities.
Add needed_quantity only when the transcript explicitly states that more of the same item is needed, required, should be ordered, should be restocked, or needs to be bought.
Keep quantity as the current counted amount, and keep needed_quantity as the amount the staff says they still need.
If no needed amount is explicitly stated, set needed_quantity to "TBD".
If the needed amount is vague, like "need more" without a number, set needed_quantity to "TBD".
Do not infer needed_quantity from par levels, common restaurant usage, or demand estimates.

Examples:
- "We have 2 boxes of tomatoes and need 6 more boxes" -> Tomatoes, quantity 2, unit boxes, needed_quantity "6 boxes"
- "We have 10 lemons and need 30 more" -> Lemons, quantity 10, unit individual, needed_quantity "30 individual"
- "We have 3 bottles of olive oil" -> Olive oil, needed_quantity "TBD"

10. Handle container fullness descriptions.
When the user gives a container and a qualitative fullness level, preserve it as a useful quantity instead of dropping the row.
Normalize common fullness phrases:
- "full" -> quantity "Full"
- "pretty full" -> quantity "Decently filled"
- "mostly full" -> quantity "Mostly full"
- "half full" or "half empty" -> quantity 0.5
- "quarter full" or "one fourth full" -> quantity 0.25
- "three quarters full" or "75% full" -> quantity 0.75
- "almost empty" or "nearly empty" -> quantity "Almost empty"
- "low" or "running low" -> quantity "Low"
Do not invent numeric quantities unless the phrase clearly maps to a common fraction like half, quarter, or three quarters.
Preserve the container as the unit.
Mark vague fullness rows as Needs Review unless the quantity is clearly numeric.

Examples:
- "a bucket of peanut butter and it's pretty full" -> Peanut butter, quantity "Decently filled", unit bucket, status Needs Review
- "one tub of ranch half full" -> Ranch, quantity 0.5, unit tub, status Partial Quantity

11. Differentiate similar items.
Keep distinct items separate when the transcript clearly separates them.

Examples:
- Tomatoes and Roma tomatoes are separate.
- Whole milk, 2 percent milk, and heavy cream are separate.
- Sparkling water and tonic water are separate.
- Tomato sauce and tomatoes are separate.
- Olive oil and canola oil are separate.
- Chicken breasts and chicken wings are separate.

12. Merge duplicates only when clearly same item and compatible units.
If same item appears multiple times with same or convertible units, merge them.

Example:
"10 eggs ... 2 dozen eggs" -> Eggs, 34 eggs

If units are incompatible and no conversion is given, keep separate or mark Possible Duplicate.

13. Status values.
Use exactly one:
- Clean
- Partial Quantity
- Missing Unit
- Needs Review
- Possible Duplicate
- Converted Unit

Priority:
Needs Review > Possible Duplicate > Missing Unit > Partial Quantity > Converted Unit > Clean

But do not mark every row Needs Review. Clean rows should be Clean. Converted rows should be Converted Unit. Partial rows should be Partial Quantity.

14. Category inference.
Infer category yourself from the item, but do not force weird categories.

Allowed categories:
- Produce
- Dairy & Eggs
- Meats
- Liquids
- Dry Goods
- Bar
- Frozen
- Supplies
- Other

Examples:
- Tomatoes, lettuce, cucumbers, cilantro -> Produce
- Milk, cream, eggs -> Dairy & Eggs
- Ground beef, chicken, bacon -> Meats
- Olive oil, canola oil, water -> Liquids unless better category is obvious
- Pizza dough, flour, rice, sugar, napkins -> Dry Goods or Supplies
- Tonic water, sparkling water, lemons/limes if bar context -> Bar
- Frozen fries, mozzarella sticks, veggie patties, ice cream -> Frozen

15. Output JSON only.
Return this exact shape:

{
  "items": [
    {
      "item_name_raw": "string",
      "item_name_clean": "string",
      "category": "Produce | Dairy & Eggs | Meats | Liquids | Dry Goods | Bar | Frozen | Supplies | Other",
      "quantity": number | string | null,
      "unit": "string" | null,
      "needed_quantity": "string",
      "status": "Clean | Partial Quantity | Missing Unit | Needs Review | Possible Duplicate | Converted Unit",
      "original_phrase": "string"
    }
  ],
  "summary": {
    "items_counted": number,
    "rows_needing_review": number,
    "partial_quantities": number,
    "missing_units": number,
    "converted_units": number,
    "possible_duplicates": number,
    "manager_insights": ["string"]
  }
}

No markdown.
No explanation.
No text outside JSON.

16. Required behavior on this hard transcript:
For this input:

"Okay I'm doing the inventory count now. I see 10 tomatoes, actually make that 12 tomatoes because there are 2 more on the bottom shelf. There are also 10 Roma tomatoes in the corner, those are separate from the regular tomatoes. I have 5 heads of lettuce and 2 boxes of cucumbers. There is cilantro too, looks like 3 bunches, wait no scratch that, it is 4 bunches of cilantro. I have 10 gallons of whole milk and 3 gallons of two percent milk. There is half a gallon of heavy cream. I see 12 dozen eggs, but 6 eggs are cracked so do not count those as usable. There are also 2 trays of 30 eggs. I have 10 ounces of ground beef and 3 chicken breasts. There are boxes of bacon on the side, I am not sure how many, actually I just checked, it is 2 boxes of bacon. I have 4 boxes of pizza dough, 2 cases of 24 water bottles, and 3 packs of 6 Coke cans. There is half a case of napkins. I have 5 bags of flour, but one bag is half empty. There are 2 ten-pound bags of rice and a quarter bag of sugar. I see 3 bottles of olive oil and one of the bottles is half empty. There are 5 gallons of canola oil and 2 jars of marinara sauce. I also have 6 cans of tomato sauce, actually change that to 8 cans of tomato sauce. Behind the bar there are 7 bottles of sparkling water, 2 cases of 12 tonic waters, and 1 dozen lemons. There are a few limes but I do not know the exact count, so that should probably be reviewed. In the freezer there are 2 boxes of frozen fries, 1 open box of mozzarella sticks, and half a box of veggie patties. There are 3 tubs of ice cream, but one tub is only a quarter full. That should be everything."

Expected clean items include:
- Tomatoes: 12 individual
- Roma tomatoes: 10 individual
- Lettuce: 5 heads
- Cucumbers: 2 boxes
- Cilantro: 4 bunches
- Whole milk: 10 gallons
- 2 percent milk: 3 gallons
- Heavy cream: 0.5 gallons
- Eggs: 198 eggs
- Ground beef: 10 ounces
- Chicken breasts: 3 individual
- Bacon: 2 boxes
- Pizza dough: 4 boxes
- Water bottles: 48 bottles
- Coke cans: 18 cans
- Napkins: 0.5 cases
- Flour: 4.5 bags
- Rice: 20 pounds
- Sugar: 0.25 bags
- Olive oil: 2.5 bottles
- Canola oil: 5 gallons
- Marinara sauce: 2 jars
- Tomato sauce: 8 cans
- Sparkling water: 7 bottles
- Tonic waters: 24 bottles
- Lemons: 12 individual
- Limes: null, Needs Review
- Frozen fries: 2 boxes
- Mozzarella sticks: 1 box
- Veggie patties: 0.5 boxes
- Ice cream: 2.25 tubs

Do not hardcode only this transcript. Use it as a behavioral example.
""".strip()


INVENTORY_COUNT_SYSTEM_PROMPT = RESTAURANT_INVENTORY_SYSTEM_PROMPT
SYSTEM_PROMPT = INVENTORY_COUNT_SYSTEM_PROMPT


RESTOCK_PLANNER_SYSTEM_PROMPT = """
You are an expert restaurant inventory manager and purchasing analyst.

Your job is to review structured evidence from a restaurant and draft a manager-reviewed purchase plan.
You are not placing orders. You must be practical, cautious, and clear.

Rules:
- Use only the provided evidence.
- Every ingredient evidence row includes ingredient_key, ingredient_name, and display_name.
- For every purchase_plan row, return the exact ingredient_key from the evidence packet.
- Do not invent new ingredient keys or ingredient names.
- Use ingredient_name/display_name only for readable display.
- If unsure which ingredient is closest, use the closest ingredient_key, set action review, and explain the uncertainty.
- Do not invent ingredients.
- Do not invent vendors.
- Do not claim exact certainty.
- Prefer practical rounded quantities over overly precise decimals.
- If units are incompatible, mark Unit Mismatch.
- If stock is unknown, mark Stock Unknown.
- If current stock is qualitative or unclear, mark Needs Review.
- If previous counts are missing or unusable, use recipe/menu evidence but mark Limited History.
- Do not overstate adaptive confidence when previous count history is missing.
- Use lower confidence when count intervals are too short, too long, unknown, or inconsistent.
- Prefer stronger confidence only when there are multiple weekly-ish usable count intervals.
- Explain when a recommendation is recipe-only versus history-adjusted.
- Use the provided history_selection and history_interval_notes to describe whether history was auto-selected, manually selected, or unavailable.
- Consider perishability, waste risk, and stockout risk.
- Consider whether the item is a direct recipe ingredient or a supply item.
- Supplies and packaging may not map perfectly to menu-item sales; use count history and stockout risk when available.
- Do not silently subtract stock when units are incompatible.
- Do not overbuy high-waste produce unless sales demand or count history strongly supports it.
- Dry goods and packaging can tolerate a practical buffer more safely than fragile produce.
- Qualitative or unclear current stock should lower confidence and require manager review.
- Explain each reason in plain English.
- Return strict JSON only.
- purchase_plan must be a JSON array.
- Do not wrap purchase_plan inside an object.
- Do not use {"items": [...]}.
- Do not use {"rows": [...]}.
- Do not return markdown.
- Do not return commentary.
- Do not write commentary outside the JSON.

Allowed action values:
- buy
- hold
- review

Allowed status values:
- Ready
- Limited History
- Stock Unknown
- Unit Mismatch
- Needs Review

Allowed confidence values:
- High
- Medium
- Low

Allowed usage_signal values:
- low
- medium
- high
- unknown

Allowed history_signal values:
- stable
- depletes_faster_than_expected
- depletes_slower_than_expected
- inconsistent
- limited_history
- unknown

Allowed risk_signal values:
- stockout_risk
- waste_risk
- balanced
- needs_review

Return this exact JSON shape:
{
  "summary": {
    "forecast_mode": "claude_adaptive" | "claude_recipe_only",
    "overall_note": "string"
  },
  "purchase_plan": [
    {
      "ingredient_key": "string",
      "ingredient": "string",
      "suggested_purchase": number | null,
      "unit": "string | null",
      "action": "buy" | "hold" | "review",
      "status": "Ready" | "Limited History" | "Stock Unknown" | "Unit Mismatch" | "Needs Review",
      "confidence": "High" | "Medium" | "Low",
      "projected_need": number | null,
      "adjusted_need": number | null,
      "current_stock": number | string | null,
      "usage_signal": "low" | "medium" | "high" | "unknown",
      "history_signal": "stable" | "depletes_faster_than_expected" | "depletes_slower_than_expected" | "inconsistent" | "limited_history" | "unknown",
      "risk_signal": "stockout_risk" | "waste_risk" | "balanced" | "needs_review",
      "reason": "string"
    }
  ],
  "learning_notes": [
    {
      "ingredient": "string",
      "note": "string"
    }
  ],
  "review_warnings": [
    {
      "ingredient": "string",
      "warning": "string"
    }
  ]
}
"""


RESTOCK_PLANNER_REFORMAT_PROMPT = """
You returned a Restock Planner response that Koe could not parse.
Convert it into Koe's required JSON schema without changing the business meaning.

Return JSON only.
The required top-level key is purchase_plan and it must be an array of item rows.
Do not return markdown.
Do not return commentary.

Required schema:
{
  "summary": {
    "forecast_mode": "claude_adaptive",
    "overall_note": "string"
  },
  "purchase_plan": [
    {
      "ingredient_key": "string",
      "ingredient": "string",
      "suggested_purchase": number or null,
      "unit": "string or null",
      "action": "buy" or "hold" or "review",
      "status": "Ready" or "Limited History" or "Stock Unknown" or "Unit Mismatch" or "Needs Review",
      "confidence": "High" or "Medium" or "Low",
      "projected_need": number or null,
      "adjusted_need": number or null,
      "current_stock": number/string/null,
      "usage_signal": "low" or "medium" or "high" or "unknown",
      "history_signal": "stable" or "depletes_faster_than_expected" or "depletes_slower_than_expected" or "inconsistent" or "limited_history" or "unknown",
      "risk_signal": "stockout_risk" or "waste_risk" or "balanced" or "needs_review",
      "reason": "string"
    }
  ],
  "learning_notes": [
    {
      "ingredient": "string",
      "note": "string"
    }
  ],
  "review_warnings": [
    {
      "ingredient": "string",
      "warning": "string"
    }
  ]
}
"""


SALES_NORMALIZATION_SYSTEM_PROMPT = """
You are Koe's sales data normalization engine for restaurant POS exports.

Your task is to convert one messy sales CSV into clean menu item sales rows for a restaurant restock planner.
Return strict JSON only. Do not return markdown or commentary.

Normalize the uploaded report into:
- item_name
- quantity_sold
- date when available
- confidence
- source_hint

Column names may vary. Common item columns include:
- item_name
- item
- item name
- menu item
- product
- product name
- name
- description
- sold item

Common quantity columns include:
- quantity_sold
- qty
- quantity
- qty sold
- quantity sold
- items sold
- units sold
- count
- net qty
- sold

Common date columns include:
- date
- business date
- order date
- transaction date
- sale date

Ignore:
- category headers
- subtotal rows
- grand total rows
- tax rows
- tips
- discounts
- refunds
- payment method rows
- blank rows
- non-menu rows
- modifiers unless they appear to be standalone sold items

Merge duplicate menu items when safe by summing quantity_sold.
Do not invent menu items or quantities.
Use confidence High, Medium, or Low.

Return this exact JSON shape:
{
  "sales_rows": [
    {
      "item_name": "Crispy Chicken Sandwich",
      "quantity_sold": 120,
      "date": "2026-07-20",
      "confidence": "High",
      "source_hint": "Matched from Product Name and Qty Sold columns"
    }
  ],
  "warnings": [
    {
      "message": "Some rows looked like modifiers and were ignored."
    }
  ],
  "normalization_summary": {
    "rows_read": 200,
    "sales_rows_extracted": 36,
    "columns_detected": {
      "item_name": "Product Name",
      "quantity_sold": "Qty Sold",
      "date": "Business Date"
    }
  }
}
"""

ALLOWED_STATUSES = {
    "Clean",
    "Partial Quantity",
    "Missing Unit",
    "Needs Review",
    "Possible Duplicate",
    "Converted Unit",
}
REVIEW_STATUSES = {"Needs Review", "Possible Duplicate", "Missing Unit"}
ALLOWED_CATEGORIES = {
    "Produce",
    "Dairy & Eggs",
    "Proteins",
    "Bakery",
    "Sauces & Condiments",
    "Oils & Liquids",
    "Beverages",
    "Dry Goods",
    "Frozen",
    "Supplies",
    "Uncategorized",
    # Legacy labels still accepted from older prompts/responses and normalized
    # below to the current report categories.
    "Meats",
    "Liquids",
    "Bar",
    "Other",
}
QUALITATIVE_CONTAINER_UNITS = {
    "bag",
    "bags",
    "bin",
    "bins",
    "bottle",
    "bottles",
    "box",
    "boxes",
    "bucket",
    "buckets",
    "case",
    "cases",
    "container",
    "containers",
    "jar",
    "jars",
    "tub",
    "tubs",
}
FRAGMENT_ONLY_NAMES = {
    "and",
    "but",
    "there are",
    "there is",
    "in the case",
    "in the case but",
    "should not be counted",
    "do not count",
    "do not count those",
    "not be counted",
    "those should not be counted",
}
FRAGMENT_NAME_PATTERNS = [
    re.compile(r"^(?:are|is|were|was|be|being)\b", re.IGNORECASE),
    re.compile(r"^(?:there\s+(?:are|is)|in\s+the\s+case)\b", re.IGNORECASE),
    re.compile(r"[\.;]\s*there\s+(?:are|is)$", re.IGNORECASE),
    re.compile(r"\b(?:should\s+not\s+be\s+counted|do\s+not\s+count|not\s+counted)\b", re.IGNORECASE),
    re.compile(r"\b(?:soft|rotten|rot|starting\s+to\s+rot|bad|spoiled|unusable|cracked)\b.*\b(?:counted|usable)\b", re.IGNORECASE),
    re.compile(r"\b(?:are|is)\s+(?:bad|spoiled|unusable|cracked|soft|rotten|brown)\b", re.IGNORECASE),
    re.compile(r"\balready\s+sliced\s+and\s+should\b", re.IGNORECASE),
    re.compile(r",?\s+\b(?:but|and)\b$", re.IGNORECASE),
    re.compile(r"\b(?:with|but|and)\s*$", re.IGNORECASE),
]

INVENTORY_COUNT_TOOL_NAME = "submit_inventory_count_rows"
INVENTORY_COUNT_TOOL = {
    "name": INVENTORY_COUNT_TOOL_NAME,
    "description": "Submit cleaned restaurant inventory count rows.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_name_raw": {"type": "string"},
                        "item_name_clean": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "quantity_label": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                        "category": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["Clean", "Needs Review", "Partial Quantity", "Missing Unit", "Possible Duplicate"],
                        },
                        "original_phrase": {"type": "string"},
                    },
                    "required": [
                        "item_name_raw",
                        "item_name_clean",
                        "quantity",
                        "quantity_label",
                        "unit",
                        "category",
                        "status",
                        "original_phrase",
                    ],
                },
            }
        },
        "required": ["items"],
    },
}


class ClaudeInventoryParseError(ValueError):
    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason)


def _extract_json_object(value: str) -> dict:
    text = value.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    decoder = json.JSONDecoder()
    parsed = None
    parse_errors: list[str] = []
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError as error:
            parse_errors.append(str(error))
            continue
        if isinstance(candidate, list):
            parsed = {"items": candidate}
            break
        if isinstance(candidate, dict):
            parsed = candidate
            break

    if parsed is None:
        detail = parse_errors[0] if parse_errors else "Claude response did not contain JSON"
        raise ValueError(detail) from None

    if not isinstance(parsed, dict):
        raise ValueError("Claude response JSON must be an object or item array")
    return parsed


def _extract_inventory_payload_from_claude_response(payload: dict) -> dict:
    content = payload.get("content") or []
    for part in content:
        if (
            isinstance(part, dict)
            and part.get("type") == "tool_use"
            and part.get("name") == INVENTORY_COUNT_TOOL_NAME
            and isinstance(part.get("input"), dict)
        ):
            return part["input"]
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    return _extract_json_object("\n".join(text_parts))


def is_inventory_sentence_fragment(value: object) -> bool:
    return _looks_like_sentence_fragment(value)


def _safe_string(value: object) -> str:
    return str(value or "").strip()


def _normalized_fragment_text(value: object) -> str:
    return re.sub(r"\s+", " ", _safe_string(value).lower().strip(" ,.;:")).strip()


def _looks_like_sentence_fragment(value: object) -> bool:
    text = _normalized_fragment_text(value)
    if not text:
        return True
    if text in FRAGMENT_ONLY_NAMES:
        return True
    if len(text.split()) <= 2 and text in {"there are", "there is", "in case", "the case"}:
        return True
    return any(pattern.search(text) for pattern in FRAGMENT_NAME_PATTERNS)


def _safe_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _format_needed_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _normalize_needed_quantity(value: object, unit: str | None = None) -> str:
    if value is None:
        return "TBD"
    if isinstance(value, (int, float)):
        quantity = float(value)
        return f"{_format_needed_number(quantity)} {unit}" if unit else _format_needed_number(quantity)

    text = re.sub(r"\s+", " ", _safe_string(value)).strip()
    if not text:
        return "TBD"
    if text.lower() in {"tbd", "unknown", "none", "null", "n/a", "na"}:
        return "TBD"
    text = re.sub(r"\bmore\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text) and unit:
        return f"{_format_needed_number(float(text))} {unit}"
    return text or "TBD"


def _debug_parse_enabled(settings) -> bool:
    return bool(getattr(settings, "debug_parse", False)) or getattr(settings, "environment", "") == "development"


def _log_parse_debug(settings, message: str, **fields: object) -> None:
    if _debug_parse_enabled(settings):
        logger.info("claude_parse_debug: %s %s", message, fields)


def _normalize_status(value: object, *, quantity: float | None, unit: str | None) -> str:
    status = _safe_string(value)
    if status in ALLOWED_STATUSES:
        return status
    if quantity is None:
        return "Needs Review"
    if not unit:
        return "Missing Unit"
    return "Clean"


def _normalize_category(value: object, *, item_name: str | None = None) -> str:
    category = _safe_string(value)
    return normalize_inventory_category(item_name, category if category in ALLOWED_CATEGORIES else None)


def _normalize_claude_item(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    item_name_raw = _safe_string(
        entry.get("item_name_raw") or entry.get("raw_item_name") or entry.get("item_name") or entry.get("name")
    ).strip(" ,.")
    item_name_clean = _safe_string(
        entry.get("item_name_clean") or entry.get("clean_item_name") or entry.get("item_name") or entry.get("name")
    ).strip(" ,.")
    if not item_name_raw and item_name_clean:
        item_name_raw = item_name_clean
    if not item_name_clean and item_name_raw:
        item_name_clean = item_name_raw
    if not item_name_clean:
        return None
    if _looks_like_sentence_fragment(item_name_clean):
        return None
    if item_name_raw == item_name_clean and _looks_like_sentence_fragment(item_name_raw):
        return None

    raw_quantity = entry.get("quantity")
    quantity = _safe_float(raw_quantity)
    quantity_label = None
    fullness_numeric = False
    if quantity is None and isinstance(raw_quantity, str) and _safe_string(raw_quantity):
        fullness_quantity, fullness_label = _normalize_fullness(raw_quantity)
        if fullness_quantity is not None:
            quantity = fullness_quantity
            fullness_numeric = True
        elif fullness_label:
            quantity_label = fullness_label
    raw_unit = entry.get("unit")
    raw_unit_text = _safe_string(raw_unit).lower()
    unit = normalize_unit(_safe_string(raw_unit)) if raw_unit is not None and _safe_string(raw_unit) else None
    if unit and (quantity_label or fullness_numeric) and raw_unit_text in QUALITATIVE_CONTAINER_UNITS:
        unit = _container_unit(raw_unit_text)
    status = _normalize_status(entry.get("status"), quantity=quantity, unit=unit)
    if not entry.get("status") and fullness_numeric:
        status = "Partial Quantity"
    if not entry.get("status") and quantity_label:
        status = "Needs Review"
    if not entry.get("status") and entry.get("partial_detail"):
        status = "Partial Quantity"
    if not entry.get("status") and entry.get("needs_review"):
        status = "Needs Review"
    original_phrase = _safe_string(entry.get("original_phrase") or entry.get("raw_phrase") or item_name_raw or item_name_clean)

    item = {
        "item_name_raw": item_name_raw,
        "item_name_clean": item_name_clean,
        "category": _normalize_category(entry.get("category"), item_name=item_name_clean),
        "quantity": quantity,
        "unit": unit,
        "needed_quantity": _normalize_needed_quantity(entry.get("needed_quantity"), unit),
        "status": status,
        "original_phrase": original_phrase,
    }
    if quantity_label:
        item["quantity_label"] = quantity_label
    return item


def _summary_from_items(items: list[dict], summary: dict | None = None) -> dict:
    source = summary if isinstance(summary, dict) else {}
    partial_quantities = sum(1 for item in items if item["status"] == "Partial Quantity")
    missing_units = sum(1 for item in items if item["status"] == "Missing Unit")
    converted_units = sum(1 for item in items if item["status"] == "Converted Unit")
    possible_duplicates = sum(1 for item in items if item["status"] == "Possible Duplicate")
    rows_needing_review = sum(1 for item in items if item["status"] in REVIEW_STATUSES or item["quantity"] is None)

    insights = source.get("manager_insights")
    if not isinstance(insights, list):
        insights = []
    normalized_insights = [_safe_string(insight) for insight in insights if _safe_string(insight)][:5]
    if not normalized_insights:
        if not items:
            normalized_insights = ["No inventory items were detected."]
        elif rows_needing_review:
            verb = "needs" if rows_needing_review == 1 else "need"
            normalized_insights = [f"{rows_needing_review} row{'s' if rows_needing_review != 1 else ''} {verb} manager review before export."]
        else:
            normalized_insights = [f"{len(items)} item{'s' if len(items) != 1 else ''} parsed and ready for review."]

    return {
        "items_counted": _safe_int(source.get("items_counted"), len(items)),
        "rows_needing_review": _safe_int(source.get("rows_needing_review"), rows_needing_review),
        "partial_quantities": _safe_int(source.get("partial_quantities"), partial_quantities),
        "missing_units": _safe_int(source.get("missing_units"), missing_units),
        "converted_units": _safe_int(source.get("converted_units"), converted_units),
        "possible_duplicates": _safe_int(source.get("possible_duplicates"), possible_duplicates),
        "manager_insights": normalized_insights,
    }


def _inventory_payload_items(payload: dict) -> list:
    raw_items = payload.get("items")
    if raw_items is None:
        raw_items = payload.get("entries", [])
    if not isinstance(raw_items, list):
        raise ValueError("Claude response items must be a list")
    return raw_items


def normalize_claude_inventory_payload(payload: dict, *, reject_fragment_heavy: bool = False) -> dict:
    raw_items = _inventory_payload_items(payload)
    fragment_rows = 0
    items = []
    for entry in raw_items:
        if isinstance(entry, dict):
            raw_name = (
                entry.get("item_name_clean")
                or entry.get("clean_item_name")
                or entry.get("item_name")
                or entry.get("name")
                or entry.get("item_name_raw")
                or entry.get("raw_item_name")
            )
            if _looks_like_sentence_fragment(raw_name):
                fragment_rows += 1
                continue
        item = _normalize_claude_item(entry)
        if item:
            items.append(item)

    total_rows = len(raw_items)
    if reject_fragment_heavy and total_rows and not items and fragment_rows / total_rows > 0.20:
        raise ValueError(
            f"Claude inventory response contained too many sentence-fragment rows "
            f"({fragment_rows}/{total_rows})"
        )
    return {"items": items, "summary": _summary_from_items(items, payload.get("summary"))}


def _coerce_candidate(entry: dict) -> ParsedCandidate | None:
    if not isinstance(entry, dict):
        return None

    item_name = str(entry.get("item_name_clean") or entry.get("item_name") or "").strip(" ,.")
    if not item_name:
        return None

    raw_quantity = entry.get("quantity")
    quantity = _safe_float(raw_quantity)
    quantity_label = _safe_string(entry.get("quantity_label")) or None
    fullness_numeric = False
    if quantity is None and not quantity_label and isinstance(raw_quantity, str) and _safe_string(raw_quantity):
        fullness_quantity, fullness_label = _normalize_fullness(raw_quantity)
        if fullness_quantity is not None:
            quantity = fullness_quantity
            fullness_numeric = True
        else:
            quantity_label = fullness_label

    status = _safe_string(entry.get("status"))
    if not status and quantity_label:
        status = "Needs Review"
    if not status and fullness_numeric:
        status = "Partial Quantity"
    raw_unit_text = _safe_string(entry.get("unit")).lower()
    unit = normalize_unit(str(entry.get("unit"))) if entry.get("unit") else None
    if unit and (quantity_label or fullness_numeric) and raw_unit_text in QUALITATIVE_CONTAINER_UNITS:
        unit = _container_unit(raw_unit_text)
    partial_detail = entry.get("partial_detail") or (entry.get("original_phrase") if status == "Partial Quantity" else None)
    review_reason = entry.get("review_reason") or (entry.get("original_phrase") if status in REVIEW_STATUSES else None)
    if quantity is None and status in REVIEW_STATUSES and unit == "individual":
        unit = None
    unit = normalize_obvious_item_unit(item_name, unit)
    resolved_unit = unit if unit is not None else None if quantity is None and status in REVIEW_STATUSES else "individual"
    return ParsedCandidate(
        raw_phrase=str(entry.get("original_phrase") or entry.get("raw_phrase") or entry.get("item_name_raw") or item_name),
        quantity=quantity,
        unit=resolved_unit,
        item_name=item_name,
        partial_detail=str(partial_detail) if partial_detail else None,
        needs_review=status in REVIEW_STATUSES or bool(entry.get("needs_review")),
        review_reason=str(review_reason) if review_reason else None,
        status=status or None,
        category=normalize_inventory_category(item_name, _safe_string(entry.get("category")) or None),
        needed_quantity=_normalize_needed_quantity(entry.get("needed_quantity"), resolved_unit),
        quantity_label=quantity_label,
    )


def parse_inventory_json_with_claude(transcript: str) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai:
        raise RuntimeError("External AI integrations are disabled")
    if (settings.text_ai_provider or "claude").lower() != "claude":
        raise RuntimeError("Text AI provider is not Claude")
    if not settings.is_claude_configured:
        raise RuntimeError("Claude is not configured")

    def post_claude(message: str, *, system_prompt: str, use_tool: bool = True, max_tokens: int = 5000) -> dict:
        request_json = {
            "model": settings.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": message}],
        }
        if use_tool:
            request_json["tools"] = [INVENTORY_COUNT_TOOL]
            request_json["tool_choice"] = {"type": "tool", "name": INVENTORY_COUNT_TOOL_NAME}

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=request_json,
            timeout=25,
        )
        if response.status_code >= 400:
            message = f"Claude request failed with status {response.status_code}"
            try:
                error_body = response.json()
                provider_message = error_body.get("error", {}).get("message")
                if provider_message:
                    message = provider_message
            except ValueError:
                pass
            raise RuntimeError(message)
        response_payload = response.json()
        content = response_payload.get("content") or []
        content_types = [part.get("type") for part in content if isinstance(part, dict)]
        _log_parse_debug(
            settings,
            "inventory_claude_raw_response_type",
            model=settings.anthropic_model,
            content_types=content_types,
            used_tool_request=use_tool,
        )
        return response_payload

    def parse_and_normalize(payload: dict, *, attempt: str) -> dict:
        parsed = _extract_inventory_payload_from_claude_response(payload)
        raw_items = _inventory_payload_items(parsed)
        fragment_rows = 0
        for entry in raw_items:
            if isinstance(entry, dict):
                raw_name = (
                    entry.get("item_name_clean")
                    or entry.get("clean_item_name")
                    or entry.get("item_name")
                    or entry.get("name")
                    or entry.get("item_name_raw")
                    or entry.get("raw_item_name")
                )
                if _looks_like_sentence_fragment(raw_name):
                    fragment_rows += 1
        normalized = normalize_claude_inventory_payload(parsed, reject_fragment_heavy=True)
        if not normalized["items"]:
            raise ValueError("Claude inventory response had zero valid item rows after validation")
        _log_parse_debug(
            settings,
            "inventory_claude_rows_extracted_count",
            model=settings.anthropic_model,
            attempt=attempt,
            valid_json=True,
            item_count=len(raw_items),
            first_2_raw_items=raw_items[:2] if isinstance(raw_items, list) else [],
        )
        _log_parse_debug(
            settings,
            "inventory_claude_rows_after_validation_count",
            model=settings.anthropic_model,
            attempt=attempt,
            item_count=len(normalized["items"]),
            first_2_normalized_entries=normalized["items"][:2],
        )
        _log_parse_debug(
            settings,
            "inventory_rows_dropped_as_fragments_count",
            model=settings.anthropic_model,
            attempt=attempt,
            dropped_count=fragment_rows,
        )
        return normalized

    primary_message = (
        "Parse this restaurant inventory count transcript.\n\n"
        "You are parsing restaurant inventory counts. Return only real inventory items. Never create rows from "
        "sentence fragments. Handle spoiled/unusable quantities inside the real item row. If a transcript says "
        '"22 tomatoes but 6 are bad," return tomatoes quantity 16 or mark Needs Review. Do not create a separate '
        'row for "6 are bad." If a transcript says "1 case of lemons with 24 in the case, but 7 lemons are bad," '
        'return lemons quantity 17 individual or Needs Review. Do not create rows for "lemons with" or '
        '"in the case."\n\n'
        f"{transcript}"
    )
    _log_parse_debug(settings, "inventory_claude_attempt_started", model=settings.anthropic_model, attempt="primary")
    primary_payload = post_claude(primary_message, system_prompt=INVENTORY_COUNT_SYSTEM_PROMPT, use_tool=True)
    primary_raw_text = "\n".join(
        part.get("text", "") for part in (primary_payload.get("content") or []) if isinstance(part, dict) and part.get("type") == "text"
    )
    try:
        return parse_and_normalize(primary_payload, attempt="primary")
    except Exception as primary_error:
        _log_parse_debug(
            settings,
            "raw_claude_json",
            model=settings.anthropic_model,
            attempt="primary",
            valid_json=False,
            error_type=type(primary_error).__name__,
        )

    repair_message = (
        "Return only valid JSON matching the inventory schema. Do not add commentary. Do not change the inventory "
        "meaning. Support this exact shape: {\"items\":[{\"item_name_raw\":\"string\","
        "\"item_name_clean\":\"string\",\"quantity\":number_or_null,\"quantity_label\":string_or_null,"
        "\"unit\":\"string\",\"category\":\"string\",\"status\":\"Clean or Needs Review or Partial Quantity or "
        "Missing Unit or Possible Duplicate\",\"original_phrase\":\"string\"}]}.\n\n"
        "Malformed Claude response to repair:\n"
        f"{primary_raw_text or json.dumps(primary_payload)}"
    )
    repair_error: Exception | None = None
    try:
        _log_parse_debug(settings, "inventory_claude_attempt_started", model=settings.anthropic_model, attempt="repair")
        repair_payload = post_claude(repair_message, system_prompt=INVENTORY_COUNT_SYSTEM_PROMPT, use_tool=False, max_tokens=5000)
        return parse_and_normalize(repair_payload, attempt="repair")
    except Exception as error:
        repair_error = error
        _log_parse_debug(
            settings,
            "raw_claude_json",
            model=settings.anthropic_model,
            attempt="repair",
            valid_json=False,
            error_type=type(error).__name__,
        )

    strict_prompt = (
        "You are parsing restaurant inventory counts. Return compact valid JSON only. No markdown. No explanations. "
        "No duplicated transcript. Extract only real inventory item rows. Do not create sentence-fragment rows. "
        "Subtract spoiled, bad, cracked, rotten, or unusable quantities from the matching real item row when clear. "
        "Use {\"items\":[...]} only."
    )
    strict_message = f"Inventory transcript:\n{transcript}"
    try:
        _log_parse_debug(settings, "inventory_claude_attempt_started", model=settings.anthropic_model, attempt="strict_reparse")
        strict_payload = post_claude(strict_message, system_prompt=strict_prompt, use_tool=False, max_tokens=4000)
        return parse_and_normalize(strict_payload, attempt="strict_reparse")
    except Exception as strict_error:
        _log_parse_debug(
            settings,
            "raw_claude_json",
            model=settings.anthropic_model,
            attempt="strict_reparse",
            valid_json=False,
            error_type=type(strict_error).__name__,
        )
        raise ClaudeInventoryParseError(
            "claude_strict_reparse_failed",
            f"claude_json_parse_failed_primary; claude_json_repair_failed; claude_strict_reparse_failed: {strict_error}",
        ) from repair_error


def parse_inventory_count_with_claude(transcript: str) -> list[ParsedCandidate]:
    parsed = parse_inventory_json_with_claude(transcript)
    candidates = [_coerce_candidate(entry) for entry in parsed["items"]]
    return [candidate for candidate in candidates if candidate is not None]


def parse_inventory_with_claude(transcript: str) -> list[ParsedCandidate]:
    return parse_inventory_count_with_claude(transcript)


def generate_restock_plan_with_claude(evidence_packet: dict) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai:
        raise RuntimeError("External AI integrations are disabled")
    if (settings.text_ai_provider or "claude").lower() != "claude":
        raise RuntimeError("Text AI provider is not Claude")
    if not settings.is_claude_configured:
        raise RuntimeError("Claude is not configured")

    ingredient_count = len(evidence_packet.get("ingredients", [])) if isinstance(evidence_packet, dict) else 0
    logger.info("restock_claude_attempt_started ingredient_count=%s", ingredient_count)
    logger.info("restock_claude_model model=%s", settings.anthropic_model)
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": 7000,
            "temperature": 0,
            "system": RESTOCK_PLANNER_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Draft a manager-reviewed restock purchase plan from this evidence packet. "
                        "Return strict JSON only.\n\n"
                        f"{json.dumps(evidence_packet, ensure_ascii=True, default=str)}"
                    ),
                }
            ],
        },
        timeout=45,
    )
    if response.status_code >= 400:
        message = f"Claude request failed with status {response.status_code}"
        try:
            error_body = response.json()
            provider_message = error_body.get("error", {}).get("message")
            if provider_message:
                message = provider_message
        except ValueError:
            pass
        raise RuntimeError(message)

    payload = response.json()
    content = payload.get("content") or []
    content_types = [part.get("type") for part in content if isinstance(part, dict)]
    logger.info("restock_claude_response_received content_types=%s", content_types)
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    raw_text = "\n".join(text_parts)
    parsed = _extract_json_object(raw_text)
    logger.info(
        "restock_claude_json_parsed ingredient_count=%s plan_count=%s",
        ingredient_count,
        len(parsed.get("purchase_plan", [])) if isinstance(parsed.get("purchase_plan"), list) else 0,
    )
    _log_parse_debug(
        settings,
        "restock_claude_json",
        model=settings.anthropic_model,
        ingredient_count=ingredient_count,
        plan_count=len(parsed.get("purchase_plan", [])) if isinstance(parsed.get("purchase_plan"), list) else 0,
    )
    return parsed


def reformat_restock_plan_with_claude(raw_response: object) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai:
        raise RuntimeError("External AI integrations are disabled")
    if (settings.text_ai_provider or "claude").lower() != "claude":
        raise RuntimeError("Text AI provider is not Claude")
    if not settings.is_claude_configured:
        raise RuntimeError("Claude is not configured")

    logger.info("restock_claude_repair_attempt_started")
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": 5000,
            "temperature": 0,
            "system": RESTOCK_PLANNER_REFORMAT_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reformat this Restock Planner response into Koe's required schema:\n\n"
                        f"{json.dumps(raw_response, ensure_ascii=True, default=str)}"
                    ),
                }
            ],
        },
        timeout=35,
    )
    if response.status_code >= 400:
        message = f"Claude repair request failed with status {response.status_code}"
        try:
            error_body = response.json()
            provider_message = error_body.get("error", {}).get("message")
            if provider_message:
                message = provider_message
        except ValueError:
            pass
        raise RuntimeError(message)

    payload = response.json()
    content = payload.get("content") or []
    content_types = [part.get("type") for part in content if isinstance(part, dict)]
    logger.info("restock_claude_repair_response_received content_types=%s", content_types)
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    parsed = _extract_json_object("\n".join(text_parts))
    logger.info(
        "restock_claude_repair_json_parsed plan_count=%s",
        len(parsed.get("purchase_plan", [])) if isinstance(parsed.get("purchase_plan"), list) else 0,
    )
    return parsed


def normalize_sales_report_with_claude(csv_text: str, *, filename: str = "sales.csv") -> dict:
    settings = get_settings()
    if not settings.enable_external_ai:
        raise RuntimeError("External AI integrations are disabled")
    if (settings.text_ai_provider or "claude").lower() != "claude":
        raise RuntimeError("Text AI provider is not Claude")
    if not settings.is_claude_configured:
        raise RuntimeError("Claude is not configured")

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": 5000,
            "temperature": 0,
            "system": SALES_NORMALIZATION_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"Normalize this restaurant sales CSV named {filename}:\n\n{csv_text}",
                }
            ],
        },
        timeout=35,
    )
    if response.status_code >= 400:
        message = f"Claude request failed with status {response.status_code}"
        try:
            error_body = response.json()
            provider_message = error_body.get("error", {}).get("message")
            if provider_message:
                message = provider_message
        except ValueError:
            pass
        raise RuntimeError(message)

    payload = response.json()
    content = payload.get("content") or []
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    parsed = _extract_json_object("\n".join(text_parts))
    _log_parse_debug(
        settings,
        "sales_normalization_claude_json",
        model=settings.anthropic_model,
        rows=len(parsed.get("sales_rows", [])) if isinstance(parsed.get("sales_rows"), list) else 0,
    )
    return parsed


def parse_inventory_with_claude_placeholder(transcript: str) -> dict:
    settings = get_settings()
    provider = settings.text_ai_provider or "claude"
    if not settings.enable_external_ai or not settings.is_claude_configured:
        return disabled_response(
            provider,
            "Claude parsing is not configured yet. Add ANTHROPIC_API_KEY and set ENABLE_EXTERNAL_AI=true.",
        )
    try:
        parsed = parse_inventory_json_with_claude(transcript)
    except RuntimeError as error:
        return {
            "configured": True,
            "provider": provider,
            "message": str(error),
            "items": [],
            "summary": _summary_from_items([]),
        }
    return {"configured": True, "provider": provider, **parsed}


def parse_inventory_with_llm_placeholder(text: str) -> dict:
    return parse_inventory_with_claude_placeholder(text)
