import json
import logging
import re

import httpx

from app.config import get_settings
from app.services.category_service import normalize_inventory_category
from app.services.voice_parse_service import ParsedCandidate, normalize_obvious_item_unit
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
- "then"
- "packs of"
- "cases of"
- "bunches wait"
- "is half empty"
- "there are"
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

9. Differentiate similar items.
Keep distinct items separate when the transcript clearly separates them.

Examples:
- Tomatoes and Roma tomatoes are separate.
- Whole milk, 2 percent milk, and heavy cream are separate.
- Sparkling water and tonic water are separate.
- Tomato sauce and tomatoes are separate.
- Olive oil and canola oil are separate.
- Chicken breasts and chicken wings are separate.

10. Merge duplicates only when clearly same item and compatible units.
If same item appears multiple times with same or convertible units, merge them.

Example:
"10 eggs ... 2 dozen eggs" -> Eggs, 34 eggs

If units are incompatible and no conversion is given, keep separate or mark Possible Duplicate.

11. Status values.
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

12. Category inference.
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

13. Output JSON only.
Return this exact shape:

{
  "items": [
    {
      "item_name_raw": "string",
      "item_name_clean": "string",
      "category": "Produce | Dairy & Eggs | Meats | Liquids | Dry Goods | Bar | Frozen | Supplies | Other",
      "quantity": number | null,
      "unit": "string" | null,
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

14. Required behavior on this hard transcript:
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


SYSTEM_PROMPT = RESTAURANT_INVENTORY_SYSTEM_PROMPT

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


def _extract_json_object(value: str) -> dict:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Claude response did not contain JSON") from None
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("Claude response JSON must be an object")
    return parsed


def _safe_string(value: object) -> str:
    return str(value or "").strip()


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

    quantity = _safe_float(entry.get("quantity"))
    raw_unit = entry.get("unit")
    unit = normalize_unit(_safe_string(raw_unit)) if raw_unit is not None and _safe_string(raw_unit) else None
    status = _normalize_status(entry.get("status"), quantity=quantity, unit=unit)
    if not entry.get("status") and entry.get("partial_detail"):
        status = "Partial Quantity"
    if not entry.get("status") and entry.get("needs_review"):
        status = "Needs Review"
    original_phrase = _safe_string(entry.get("original_phrase") or entry.get("raw_phrase") or item_name_raw or item_name_clean)

    return {
        "item_name_raw": item_name_raw,
        "item_name_clean": item_name_clean,
        "category": _normalize_category(entry.get("category"), item_name=item_name_clean),
        "quantity": quantity,
        "unit": unit,
        "status": status,
        "original_phrase": original_phrase,
    }


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


def normalize_claude_inventory_payload(payload: dict) -> dict:
    raw_items = payload.get("items")
    if raw_items is None:
        raw_items = payload.get("entries", [])
    if not isinstance(raw_items, list):
        raise ValueError("Claude response items must be a list")

    items = [item for entry in raw_items if (item := _normalize_claude_item(entry))]
    return {"items": items, "summary": _summary_from_items(items, payload.get("summary"))}


def _coerce_candidate(entry: dict) -> ParsedCandidate | None:
    if not isinstance(entry, dict):
        return None

    item_name = str(entry.get("item_name_clean") or entry.get("item_name") or "").strip(" ,.")
    if not item_name:
        return None

    quantity = _safe_float(entry.get("quantity"))

    status = _safe_string(entry.get("status"))
    unit = normalize_unit(str(entry.get("unit"))) if entry.get("unit") else None
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
    )


def parse_inventory_json_with_claude(transcript: str) -> dict:
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
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"Parse this restaurant inventory count transcript:\n\n{transcript}",
                }
            ],
        },
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

    payload = response.json()
    content = payload.get("content") or []
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    raw_text = "\n".join(text_parts)
    try:
        parsed = _extract_json_object(raw_text)
        raw_items = parsed.get("items") if isinstance(parsed.get("items"), list) else parsed.get("entries", [])
        _log_parse_debug(
            settings,
            "raw_claude_json",
            model=settings.anthropic_model,
            valid_json=True,
            item_count=len(raw_items) if isinstance(raw_items, list) else 0,
            first_2_raw_items=raw_items[:2] if isinstance(raw_items, list) else [],
        )
    except Exception as error:
        _log_parse_debug(
            settings,
            "raw_claude_json",
            model=settings.anthropic_model,
            valid_json=False,
            error_type=type(error).__name__,
        )
        raise
    normalized = normalize_claude_inventory_payload(parsed)
    _log_parse_debug(
        settings,
        "normalized_backend_entries",
        model=settings.anthropic_model,
        item_count=len(normalized["items"]),
        first_2_normalized_entries=normalized["items"][:2],
    )
    return normalized


def parse_inventory_with_claude(transcript: str) -> list[ParsedCandidate]:
    parsed = parse_inventory_json_with_claude(transcript)
    candidates = [_coerce_candidate(entry) for entry in parsed["items"]]
    return [candidate for candidate in candidates if candidate is not None]


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
