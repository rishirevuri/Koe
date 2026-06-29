import re

from app.services.voice_parse_service import ParsedCandidate, START_PATTERN, parse_voice_text
from app.services.partial_quantity_service import parse_partial_quantity
from app.utils.units import UNITS_PATTERN, normalize_unit


ITEM_FIRST_PATTERN = re.compile(
    rf"(?P<item>[A-Za-z][A-Za-z\s]+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit>{UNITS_PATTERN})\b",
    re.IGNORECASE,
)


def parse_upload_text(text: str) -> list[ParsedCandidate]:
    normalized = text.replace("\n", ", ").replace(";", ", ")
    candidates: list[ParsedCandidate] = []
    for part in [chunk.strip(" .") for chunk in normalized.split(",") if chunk.strip(" .")]:
        match = ITEM_FIRST_PATTERN.search(part)
        if match:
            qty = float(match.group("qty"))
            unit = normalize_unit(match.group("unit"))
            partial = parse_partial_quantity(part, qty, unit)
            candidates.append(
                ParsedCandidate(
                    raw_phrase=part,
                    quantity=partial.quantity if partial.quantity is not None else qty,
                    unit=partial.unit or unit,
                    item_name=match.group("item").strip(),
                    partial_detail=partial.partial_detail,
                    needs_review=partial.needs_review,
                    review_reason=partial.review_reason,
                )
            )
            continue

        voice_candidates = parse_voice_text(part)
        if voice_candidates:
            candidates.extend(voice_candidates)
    return candidates
