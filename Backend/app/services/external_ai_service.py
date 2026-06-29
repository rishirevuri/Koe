import json
import re

import httpx

from app.config import get_settings
from app.services.voice_parse_service import ParsedCandidate
from app.utils.units import normalize_unit


def disabled_response(provider: str, message: str) -> dict[str, bool | str]:
    return {"configured": False, "provider": provider, "message": message}


SYSTEM_PROMPT = """You parse restaurant inventory count transcripts into structured inventory rows.
Return only valid JSON. Do not include markdown.

Output shape:
{
  "entries": [
    {
      "raw_phrase": "original phrase for this item",
      "item_name": "clean item name only",
      "quantity": 10,
      "unit": "individual",
      "partial_detail": null,
      "needs_review": false,
      "review_reason": null
    }
  ]
}

Rules:
- Split every counted item into its own row.
- Remove filler and connector phrases from item names, such as "I have", "and then", "also", "we got".
- If no unit is spoken, use "individual".
- If a unit is spoken, preserve the unit meaning, such as bottles, boxes, cartons, grams, milligrams, pounds, ounces, cases, heads, bags, tubs, containers, trays, crates.
- For phrases like "3 bottles of olive oil, one of which is half empty", return quantity 2.5, unit bottles, item_name olive oil, and partial_detail.
- For vague partials like "almost empty" or "mostly full", keep the whole quantity and set needs_review true.
- Do not invent items, quantities, or units.
"""


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


def _coerce_candidate(entry: dict) -> ParsedCandidate | None:
    if not isinstance(entry, dict):
        return None

    item_name = str(entry.get("item_name") or "").strip(" ,.")
    if not item_name:
        return None

    try:
        quantity = float(entry.get("quantity"))
    except (TypeError, ValueError):
        return None

    unit = normalize_unit(str(entry.get("unit") or "individual"))
    partial_detail = entry.get("partial_detail")
    review_reason = entry.get("review_reason")
    return ParsedCandidate(
        raw_phrase=str(entry.get("raw_phrase") or item_name),
        quantity=quantity,
        unit=unit or "individual",
        item_name=item_name,
        partial_detail=str(partial_detail) if partial_detail else None,
        needs_review=bool(entry.get("needs_review")),
        review_reason=str(review_reason) if review_reason else None,
    )


def parse_inventory_with_claude(transcript: str) -> list[ParsedCandidate]:
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
    raw_entries = parsed.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError("Claude response entries must be a list")

    candidates = [_coerce_candidate(entry) for entry in raw_entries]
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
        entries = parse_inventory_with_claude(transcript)
    except RuntimeError as error:
        return {
            "configured": True,
            "provider": provider,
            "message": str(error),
            "entries": [],
        }
    return {"configured": True, "provider": provider, "entries": [entry.__dict__ for entry in entries]}


def parse_inventory_with_llm_placeholder(text: str) -> dict:
    return parse_inventory_with_claude_placeholder(text)
