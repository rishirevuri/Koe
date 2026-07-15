import re
from dataclasses import dataclass

from app.services.partial_quantity_service import parse_partial_quantity
from app.utils.units import UNIT_ALIASES, UNITS_PATTERN, normalize_unit


@dataclass
class ParsedCandidate:
    raw_phrase: str
    quantity: float | None
    unit: str | None
    item_name: str
    partial_detail: str | None
    needs_review: bool
    review_reason: str | None
    status: str | None = None
    category: str | None = None


NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
NUMBER_WORDS_PATTERN = "|".join(NUMBER_WORDS.keys())

START_PATTERN = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit>{UNITS_PATTERN})\b(?:\s+of)?\s+", re.IGNORECASE)
NUMBER_WORD_START_PATTERN = re.compile(
    rf"\b(?P<num>{NUMBER_WORDS_PATTERN})\s+(?!(?:of|is|half|quarter|fourth|three|almost|mostly|partially)\b)(?P<next>[A-Za-z][A-Za-z-]*)\b",
    re.IGNORECASE,
)
QUANTITY_START_PATTERN = re.compile(r"\b(?P<qty>\d+(?:\.\d+)?)\s+(?P<first>[A-Za-z][A-Za-z-]*)\b", re.IGNORECASE)
LEADING_NOISE = re.compile(r"^(?:we have|we've got|we got|i have|there are|there is|have|and)\s+", re.IGNORECASE)
TRAILING_CONNECTOR = re.compile(
    r"\s+(?:,?\s*)?(?:and\s+)?(?:then\s+)?(?:(?:i|we)\s+)?(?:said\s+)?(?:(?:i|we)\s+)?(?:also\s+)?(?:have|got)$",
    re.IGNORECASE,
)
TRAILING_CONNECTOR_FRAGMENT = re.compile(
    r"\s+(?:and|andn|then|also|and\s+then|andn\s+then|then\s+i|then\s+we|and\s+i|and\s+we|andn\s+i|andn\s+we)(?:\s+said)?(?:\s+also)?$",
    re.IGNORECASE,
)
PARTIAL_TAIL = re.compile(
    r"\b(?:one\s+(?:(?:of\s+)?(?:which|them)\s+)?(?:is\s+)?(?:half|quarter|fourth|three quarters|three fourths)\s+(?:empty|full)?|one\s+(?:almost empty|mostly full|partially full))\b",
    re.IGNORECASE,
)
VAGUE_QUANTITY_PATTERN = re.compile(
    r"\b(?:a few|some|several|not sure how many|unknown count|(?:i|we)\s+(?:do not|don't)\s+know(?:\s+the)?\s+exact\s+count)\b",
    re.IGNORECASE,
)
VAGUE_LEADING_ITEM_PATTERN = re.compile(
    r"\b(?P<vague>a few|some|several)\s+(?P<item>[A-Za-z][A-Za-z\s-]*?)(?=\s*(?:,|\.|;|\bbut\b|\bnot sure\b|\bunknown count\b|\bi\s+(?:do not|don't)\b|\d+\b|$))",
    re.IGNORECASE,
)
UNKNOWN_TRAILING_ITEM_PATTERN = re.compile(
    r"\b(?P<item>[A-Za-z][A-Za-z\s-]*?)\s+(?:not sure how many|unknown count|(?:i|we)\s+(?:do not|don't)\s+know(?:\s+the)?\s+exact\s+count)\b",
    re.IGNORECASE,
)
VAGUE_LEADING_WORDS = re.compile(r"^(?:a few|some|several)\s+", re.IGNORECASE)
UNKNOWN_TAIL = re.compile(
    r"\s+(?:but\s+)?(?:not sure how many|unknown count|(?:i|we)\s+(?:do not|don't)\s+know(?:\s+the)?\s+exact\s+count).*$",
    re.IGNORECASE,
)
UNUSABLE_ITEM_PATTERN = re.compile(r"\b(?:spoiled|unusable|rotten|bad|discard|throw away|thrown away)\b", re.IGNORECASE)


def _normalize_spoken_numbers(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        number = NUMBER_WORDS[match.group("num").lower()]
        return f"{number} {match.group('next')}"

    return NUMBER_WORD_START_PATTERN.sub(replace, text)


def _split_inventory_phrases(text: str) -> list[str]:
    cleaned = _normalize_spoken_numbers(text)
    cleaned = re.sub(r"\s+", " ", cleaned.replace("\n", ", ").replace(";", ", ")).strip()
    cleaned = LEADING_NOISE.sub("", cleaned)
    matches = list(QUANTITY_START_PATTERN.finditer(cleaned))
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
    cleaned = value.strip(" ,.")
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = TRAILING_CONNECTOR.sub("", cleaned).strip(" ,.")
        cleaned = TRAILING_CONNECTOR_FRAGMENT.sub("", cleaned).strip(" ,.")
        cleaned = re.sub(r"(?:,?\s+(?:and|andn|then|also))$", "", cleaned, flags=re.IGNORECASE).strip(" ,.")
    return cleaned


def normalize_obvious_item_unit(item_name: str, unit: str | None) -> str | None:
    normalized_item = re.sub(r"[^a-z0-9]+", " ", item_name.lower()).strip()
    if unit not in {None, "", "individual"}:
        return unit
    if re.search(r"\bpaper cups?\b", normalized_item):
        return "cups"
    if re.search(r"\bveggie(?: burger)? patties?\b", normalized_item):
        return "patties"
    if re.search(r"\b(?:burger|hamburger) buns?\b", normalized_item):
        return "buns"
    return unit


def _clean_vague_item_name(value: str) -> str:
    cleaned = UNKNOWN_TAIL.sub("", value).strip(" ,.")
    cleaned = VAGUE_LEADING_WORDS.sub("", cleaned).strip(" ,.")
    cleaned = LEADING_NOISE.sub("", cleaned).strip(" ,.")
    return _clean_item_name(cleaned)


def _parse_vague_quantity_phrases(text: str) -> list[ParsedCandidate]:
    candidates: list[ParsedCandidate] = []
    seen: set[str] = set()
    for pattern in (VAGUE_LEADING_ITEM_PATTERN, UNKNOWN_TRAILING_ITEM_PATTERN):
        for match in pattern.finditer(text):
            raw_phrase = match.group(0).strip(" ,.")
            if not VAGUE_QUANTITY_PATTERN.search(raw_phrase):
                continue
            item_name = _clean_vague_item_name(match.group("item"))
            if not item_name or UNUSABLE_ITEM_PATTERN.search(item_name):
                continue
            key = item_name.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                ParsedCandidate(
                    raw_phrase=raw_phrase,
                    quantity=None,
                    unit=normalize_obvious_item_unit(item_name, None),
                    item_name=item_name,
                    partial_detail=None,
                    needs_review=True,
                    review_reason="Vague or unknown quantity; confirm the count before export.",
                    status="Needs Review",
                )
            )
    return candidates


def _parse_quantity_unit_item(phrase: str) -> tuple[re.Match[str], float, str, str] | None:
    match = QUANTITY_START_PATTERN.search(phrase)
    if not match:
        return None

    qty = float(match.group("qty"))
    first_word = match.group("first")
    first_normalized = normalize_unit(first_word)
    remainder = phrase[match.end() :].strip(" ,.")

    if first_normalized in UNIT_ALIASES.values():
        item_part = re.sub(r"^of\s+", "", remainder, flags=re.IGNORECASE).strip(" ,.")
        return match, qty, first_normalized, item_part

    item_part = f"{first_word} {remainder}".strip(" ,.")
    return match, qty, normalize_obvious_item_unit(item_part, "individual") or "individual", item_part


def parse_voice_text(text: str) -> list[ParsedCandidate]:
    candidates: list[ParsedCandidate] = []
    for phrase in _split_inventory_phrases(text):
        parsed = _parse_quantity_unit_item(phrase)
        if not parsed:
            continue
        match, qty, unit, item_part = parsed
        partial_match = PARTIAL_TAIL.search(item_part)
        if partial_match:
            item_name = _clean_item_name(item_part[: partial_match.start()])
            partial_phrase = f"{match.group('qty')} {unit} {item_name}, {partial_match.group(0)}"
        else:
            item_name = _clean_item_name(item_part)
            partial_phrase = phrase

        partial = parse_partial_quantity(partial_phrase, qty, unit)
        resolved_unit = normalize_obvious_item_unit(item_name, partial.unit or unit)
        candidates.append(
            ParsedCandidate(
                raw_phrase=phrase,
                quantity=partial.quantity if partial.quantity is not None else qty,
                unit=resolved_unit,
                item_name=item_name,
                partial_detail=partial.partial_detail,
                needs_review=partial.needs_review,
                review_reason=partial.review_reason,
                status="Needs Review" if partial.needs_review else "Partial Quantity" if partial.partial_detail else "Clean",
            )
        )
    candidates.extend(_parse_vague_quantity_phrases(text))
    return candidates
