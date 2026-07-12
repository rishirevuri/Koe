import json
import re

import httpx

from app.config import get_settings
from app.services.voice_parse_service import ParsedCandidate
from app.utils.units import normalize_unit


def disabled_response(provider: str, message: str) -> dict[str, bool | str]:
    return {"configured": False, "provider": provider, "message": message}


RESTAURANT_INVENTORY_SYSTEM_PROMPT = """
You are Koe, an AI inventory assistant for restaurants.

Your job is to convert messy spoken or typed restaurant inventory counts into clean, structured, manager-ready inventory data.

The input may be:
- raw voice transcript
- typed inventory notes
- incomplete staff shorthand
- messy quantities
- partial containers
- restaurant-specific item names
- area-specific counts

You must extract only the inventory items actually mentioned. Do not invent items, prices, vendors, par levels, or categories that were not stated or provided in context.

Core output requirement:
Return only valid JSON. No markdown. No comments. No prose outside JSON.

Required JSON shape:

{
  "items": [
    {
      "item_name_raw": "string",
      "item_name_clean": "string",
      "quantity": number | null,
      "unit": "string" | null,
      "status": "Clean" | "Partial Quantity" | "Missing Unit" | "Needs Review" | "Possible Duplicate" | "Converted Unit",
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

Parsing rules:

1. Item extraction
- Extract every inventory item mentioned.
- Normalize item names into clean title case.
- Do not include filler words.
- Do not invent missing items.
- If an item name is unclear, keep the best extracted phrase and mark status as "Needs Review".
- If two phrases likely refer to the same item, merge them only when highly confident. Otherwise keep both and mark status "Possible Duplicate".
- "olive oil" -> "Olive oil"
- "roma tomatoes" -> "Roma tomatoes"
- "chicken breast" -> "Chicken breast"
- "OO" should only become "Olive oil" if restaurant-specific memory says so. Otherwise mark Needs Review.

2. Quantity extraction
- Convert spoken numbers into numeric values.
- Handle whole numbers, decimals, fractions, and mixed quantities.
- Convert "one", "two", "three" etc. to numbers.
- Convert "half" to 0.5.
- Convert "quarter" to 0.25.
- Convert "third" to approximately 0.33 unless exact precision is needed.
- Convert "one and a half" to 1.5.
- Convert "two and a quarter" to 2.25.
- If quantity is vague, set quantity to null and status "Needs Review".
- "three bottles" -> quantity 3
- "2.5 cases" -> quantity 2.5
- "one half bag" -> quantity 0.5
- "a couple boxes" -> quantity null, Needs Review
- "a few tomatoes" -> quantity null, Needs Review
- "some lettuce" -> quantity null, Needs Review

3. Dozen and pack conversions
- Convert dozens to individual units when the unit is countable.
- "1 dozen eggs" = 12 eggs.
- "10 dozen eggs" = 120 eggs.
- "half dozen eggs" = 6 eggs.
- "2 dozen buns" = 24 buns.
- Mark status as "Converted Unit".
- original_phrase should preserve the phrase that caused the conversion.
- Use common count conversions: 1 dozen = 12; 1 half dozen = 6; 1 gross = 144, if mentioned.
- "case of 24" means 24 individual units if the item is counted individually.
- "2 cases of 24 waters" means 48 waters.
- "3 packs of 6 sodas" means 18 sodas.
- "4 trays of 30 eggs" means 120 eggs.
- If the item is normally managed by case/pack and the user clearly wants cases, preserve the case/pack unit instead of converting. Prefer conversion only when the phrase explicitly states pack size or countable unit.

4. Partial container handling
- Handle partial containers carefully.
- If a phrase says a container is partially full or partially empty, convert when possible.
- If exact partial amount is unclear, mark Needs Review.
- "3 bottles of olive oil, one is half empty" -> 2.5 bottles, Partial Quantity.
- "2 full boxes and one half box of tomatoes" -> 2.5 boxes, Partial Quantity.
- "one case plus a quarter case" -> 1.25 cases, Partial Quantity.
- "3 bags, one is almost empty" -> quantity 3, status Needs Review, original_phrase includes the unclear partial phrase.
- "half a container of sauce" -> 0.5 containers, Partial Quantity.
- "one open bottle and two sealed bottles" -> 3 bottles, Clean unless amount in open bottle is unclear.

5. Units
- Normalize units into simple lowercase plural units when possible.
- Keep units consistent.
- Do not change meaning.
- If unit is missing, set unit to null and status "Missing Unit".
- Common units: bottles, boxes, cases, bags, heads, pounds, ounces, gallons, quarts, pints, liters, cans, jars, trays, containers, packs, bunches, each, eggs, loaves, tubs, sleeves, rolls, bins.
- "lbs" -> "pounds"; "oz" -> "ounces"; "gal" -> "gallons"; "ea" -> "each".
- "ct" -> "count" or "each" depending on phrase.
- "heads of lettuce" -> unit "heads".
- "bunches of cilantro" -> unit "bunches".

6. Unit conversions
- Only convert units when the conversion is explicitly stated or standard and safe.
- Safe conversions: dozen -> individual count; half dozen -> individual count; pack of N -> N individual units if item is countable; case of N -> N individual units if item is countable; lbs -> pounds; oz -> ounces; gal -> gallons.
- Do not guess conversions like case to pounds, box to pounds, bag to ounces, or container to servings unless the user provides the conversion.
- "2 cases of 24 water bottles" -> 48 bottles, Converted Unit.
- "3 cases of tomatoes" -> 3 cases, Clean.
- "5 boxes of lettuce" -> 5 boxes, Clean.
- "2 ten-pound bags of flour" -> 20 pounds if clearly spoken as ten-pound bags, Converted Unit.
- "4 five-pound tubs of yogurt" -> 20 pounds or 4 tubs depending wording; if unclear, keep 4 tubs and note package size.

7. Restaurant speech patterns
- Handle natural staff phrasing: "we got", "there are", "left with", "on hand", "in the walk-in", "in dry storage", "behind the bar", "plus", "and then", "also", "scratch that", "actually", "make that".
- If the speaker corrects themselves, use the corrected value.
- "We have 4 boxes of tomatoes, actually 5" -> 5 boxes.
- "2 bags of flour, no 3 bags" -> 3 bags.
- "scratch the lettuce" -> exclude lettuce if clearly canceled.
- "not olive oil, canola oil" -> Canola oil.

8. Duplicate handling
- If the same item appears multiple times, combine quantities only when same item and same unit are clearly repeated.
- If units differ and conversion is not safe, keep separate rows or mark Possible Duplicate.
- "2 boxes tomatoes and 3 boxes tomatoes" -> 5 boxes Tomatoes.
- "2 cases tomatoes and 5 pounds tomatoes" -> keep separate or mark Possible Duplicate because units differ.
- "olive oil 2 bottles, extra virgin olive oil 1 bottle" -> separate items unless restaurant memory says they are same.

9. Status rules
Use exactly one of these statuses:
- Clean
- Partial Quantity
- Missing Unit
- Needs Review
- Possible Duplicate
- Converted Unit

Status selection:
- Clean: item, quantity, and unit are clear.
- Partial Quantity: partial container/fraction was handled.
- Missing Unit: item and quantity are clear but unit is missing.
- Needs Review: quantity/item/unit is vague or ambiguous.
- Possible Duplicate: same/similar item appears more than once and merge is uncertain.
- Converted Unit: quantity was converted from dozen, pack size, case size, or similar.
- If multiple statuses apply, choose the most important:
Needs Review > Possible Duplicate > Missing Unit > Partial Quantity > Converted Unit > Clean.

10. Row fields
- item_name_raw is the raw item name or best available item phrase before cleaning.
- item_name_clean is the normalized clean item name in title case.
- original_phrase is the exact phrase or best available source phrase from the transcript.
- Do not include manager_note on row objects.
- Do not include needs_review on row objects.

11. Manager insights
- summary.manager_insights should contain 1-5 useful plain-English insights.
- Do not overstate.
- Do not invent business conclusions.
- Base insights only on parsed rows and provided context.
- Useful insight types: number of rows needing review, partial quantities detected, converted units detected, missing units detected, duplicate risk, whether data is ready to export.
- Examples:
"Four items were parsed and are ready for review."
"One partial quantity was normalized; review it if exact inventory levels matter."
"Two rows need manager review before export."
"Several quantities were converted from package counts into individual units."

12. Restaurant-specific memory
- If restaurant-specific context is provided, use it.
- Context may include preferred item names, common abbreviations, preferred units, previously corrected names, known area labels, common inventory categories.
- If context says "OO means Olive oil", parse OO as Olive oil.
- If context says "Tomatoes are usually counted in boxes", then if the user says "5 tomatoes" do not automatically change to boxes. Only use context to flag or suggest review, not override clear user input.

13. Area context
- If the request includes an area like Walk-in, Dry Storage, Bar, Kitchen, or Freezer, use it only for notes/context if needed.
- Do not add area into item_name.
- Do not invent items based on the area.

14. Safety and reliability
- Return JSON only.
- No markdown.
- No explanations outside JSON.
- Make valid parseable JSON.
- Do not include trailing commas.
- If the transcript is empty or unrelated to inventory, return empty items and a manager insight saying no inventory items were detected.
- If uncertain, mark Needs Review instead of guessing.
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


def _normalize_status(value: object, *, quantity: float | None, unit: str | None) -> str:
    status = _safe_string(value)
    if status in ALLOWED_STATUSES:
        return status
    if quantity is None:
        return "Needs Review"
    if not unit:
        return "Missing Unit"
    return "Clean"


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
    if quantity is None:
        quantity = 0.0

    status = _safe_string(entry.get("status"))
    unit = normalize_unit(str(entry.get("unit") or "individual"))
    partial_detail = entry.get("partial_detail") or (entry.get("original_phrase") if status == "Partial Quantity" else None)
    review_reason = entry.get("review_reason") or (entry.get("original_phrase") if status in REVIEW_STATUSES else None)
    return ParsedCandidate(
        raw_phrase=str(entry.get("original_phrase") or entry.get("raw_phrase") or entry.get("item_name_raw") or item_name),
        quantity=quantity,
        unit=unit or "individual",
        item_name=item_name,
        partial_detail=str(partial_detail) if partial_detail else None,
        needs_review=status in REVIEW_STATUSES or bool(entry.get("needs_review")),
        review_reason=str(review_reason) if review_reason else None,
        status=status or None,
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
            "max_tokens": 1200,
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
    parsed = _extract_json_object("\n".join(text_parts))
    return normalize_claude_inventory_payload(parsed)


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
