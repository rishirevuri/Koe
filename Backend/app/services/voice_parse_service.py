import re
from dataclasses import dataclass

from app.services.partial_quantity_service import parse_partial_quantity
from app.utils.units import UNITS_PATTERN, normalize_unit


@dataclass
class ParsedCandidate:
    raw_phrase: str
    quantity: float
    unit: str
    item_name: str
    partial_detail: str | None
    needs_review: bool
    review_reason: str | None


START_PATTERN = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit>{UNITS_PATTERN})\b(?:\s+of)?\s+", re.IGNORECASE)
LEADING_NOISE = re.compile(r"^(?:we have|there are|there is|have|and)\s+", re.IGNORECASE)
PARTIAL_TAIL = re.compile(
    r"\b(?:one\s+(?:of which\s+)?(?:is\s+)?(?:half|quarter|fourth|three quarters|three fourths)\s+(?:empty|full)?|one\s+(?:almost empty|mostly full|partially full))\b",
    re.IGNORECASE,
)


def _split_inventory_phrases(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.replace("\n", ", ").replace(";", ", ")).strip()
    cleaned = LEADING_NOISE.sub("", cleaned)
    matches = list(START_PATTERN.finditer(cleaned))
    phrases: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        phrase = cleaned[start:end].strip(" ,.")
        phrase = re.sub(r"^(?:and)\s+", "", phrase, flags=re.IGNORECASE)
        phrase = re.sub(r",?\s+and$", "", phrase, flags=re.IGNORECASE).strip(" ,.")
        if phrase:
            phrases.append(phrase)
    return phrases


def _clean_item_name(value: str) -> str:
    return re.sub(r"(?:,?\s+and)$", "", value.strip(" ,."), flags=re.IGNORECASE).strip(" ,.")


def parse_voice_text(text: str) -> list[ParsedCandidate]:
    candidates: list[ParsedCandidate] = []
    for phrase in _split_inventory_phrases(text):
        match = START_PATTERN.search(phrase)
        if not match:
            continue
        qty = float(match.group("qty"))
        unit = normalize_unit(match.group("unit"))
        item_part = phrase[match.end() :].strip(" ,.")
        partial_match = PARTIAL_TAIL.search(item_part)
        if partial_match:
            item_name = _clean_item_name(item_part[: partial_match.start()])
            partial_phrase = f"{match.group('qty')} {match.group('unit')} {item_name}, {partial_match.group(0)}"
        else:
            item_name = _clean_item_name(item_part)
            partial_phrase = phrase

        partial = parse_partial_quantity(partial_phrase, qty, unit)
        candidates.append(
            ParsedCandidate(
                raw_phrase=phrase,
                quantity=partial.quantity if partial.quantity is not None else qty,
                unit=partial.unit or unit,
                item_name=item_name,
                partial_detail=partial.partial_detail,
                needs_review=partial.needs_review,
                review_reason=partial.review_reason,
            )
        )
    return candidates
