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
    needed_quantity: str = "TBD"
    quantity_label: str | None = None


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
NEEDED_VERB_PATTERN = (
    r"(?:need(?:s|ed)?(?:\s+to\s+(?:order|restock|buy))?|require(?:s|d)?|"
    r"order(?:ed)?|restock(?:ed)?|buy|bought|should\s+(?:order|restock|buy))"
)
NEEDED_START_PREFIX = re.compile(rf"\b{NEEDED_VERB_PATTERN}\s*$", re.IGNORECASE)
NEEDED_QUANTITY_PATTERN = re.compile(
    rf"\b{NEEDED_VERB_PATTERN}\s+"
    rf"(?P<qty>\d+(?:\.\d+)?|{NUMBER_WORDS_PATTERN})"
    rf"(?:\s+(?:more\b(?:\s+(?P<unit_after_more>{UNITS_PATTERN}))?|(?P<unit>{UNITS_PATTERN})))?",
    re.IGNORECASE,
)
CONTAINER_UNITS = {
    "bag": "bag",
    "bags": "bag",
    "bin": "bin",
    "bins": "bin",
    "bottle": "bottle",
    "bottles": "bottle",
    "box": "box",
    "boxes": "box",
    "bucket": "bucket",
    "buckets": "bucket",
    "case": "case",
    "cases": "case",
    "container": "container",
    "containers": "container",
    "jar": "jar",
    "jars": "jar",
    "tub": "tub",
    "tubs": "tub",
}
CONTAINER_PATTERN = "|".join(sorted(CONTAINER_UNITS.keys(), key=len, reverse=True))
CONTAINER_START_PATTERN = re.compile(
    rf"\b(?P<amount>a|an|one|1)\s+(?P<container>{CONTAINER_PATTERN})\s+of\s+",
    re.IGNORECASE,
)
FULLNESS_PATTERN = re.compile(
    r"\b(?:(?:it(?:'|’)?s|it\s+is|they(?:'|’)?re|they\s+are|is|are)\s+)?"
    r"(?P<fullness>"
    r"three\s+(?:quarters|fourths)\s+full|75\s*%\s*full|"
    r"(?:about\s+)?(?:a\s+)?quarter\s+full|(?:about\s+)?one\s+fourth\s+full|"
    r"half\s+(?:full|empty)|pretty\s+full|mostly\s+full|almost\s+empty|nearly\s+empty|running\s+low|low|full"
    r")\b",
    re.IGNORECASE,
)


def _normalize_spoken_numbers(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        number = NUMBER_WORDS[match.group("num").lower()]
        return f"{number} {match.group('next')}"

    return NUMBER_WORD_START_PATTERN.sub(replace, text)


def _split_inventory_phrases(text: str) -> list[str]:
    cleaned = _normalize_spoken_numbers(text)
    cleaned = re.sub(r"\s+", " ", cleaned.replace("\n", ", ").replace(";", ", ")).strip()
    cleaned = LEADING_NOISE.sub("", cleaned)
    matches = [match for match in QUANTITY_START_PATTERN.finditer(cleaned) if not _is_needed_quantity_start(cleaned, match)]
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


def _is_needed_quantity_start(text: str, match: re.Match[str]) -> bool:
    prefix = text[max(0, match.start() - 48) : match.start()]
    return bool(NEEDED_START_PREFIX.search(prefix))


def _clean_item_name(value: str) -> str:
    cleaned = value.strip(" ,.")
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = TRAILING_CONNECTOR.sub("", cleaned).strip(" ,.")
        cleaned = TRAILING_CONNECTOR_FRAGMENT.sub("", cleaned).strip(" ,.")
        cleaned = re.sub(r"(?:,?\s+(?:and|andn|then|also))$", "", cleaned, flags=re.IGNORECASE).strip(" ,.")
    return cleaned


def _format_needed_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _quantity_text_to_float(value: str) -> float:
    normalized = value.lower().strip()
    if normalized in NUMBER_WORDS:
        return float(NUMBER_WORDS[normalized])
    return float(normalized)


def _container_unit(value: str) -> str:
    normalized = value.lower().strip()
    return CONTAINER_UNITS.get(normalized, normalized)


def _extract_needed_quantity(value: str, fallback_unit: str | None = None) -> str:
    match = NEEDED_QUANTITY_PATTERN.search(value)
    if not match:
        return "TBD"
    quantity = _quantity_text_to_float(match.group("qty"))
    unit = match.group("unit_after_more") or match.group("unit")
    normalized_unit = normalize_unit(unit) if unit else fallback_unit
    if normalized_unit and quantity == 1 and (unit or fallback_unit or "").lower() in CONTAINER_UNITS:
        normalized_unit = _container_unit(unit or fallback_unit or "")
    if normalized_unit:
        return f"{_format_needed_number(quantity)} {normalized_unit}"
    return _format_needed_number(quantity)


def _remove_needed_quantity_clause(value: str) -> str:
    return NEEDED_QUANTITY_PATTERN.sub("", value).strip(" ,.")


def _normalize_fullness(value: str) -> tuple[float | None, str | None]:
    normalized = re.sub(r"\s+", " ", value.lower().replace("’", "'")).strip()
    if normalized in {"half full", "half empty"}:
        return 0.5, None
    if normalized in {"quarter full", "a quarter full", "about quarter full", "about a quarter full", "one fourth full", "about one fourth full"}:
        return 0.25, None
    if normalized in {"three quarters full", "three fourths full", "75% full", "75 % full"}:
        return 0.75, None
    if normalized in {"pretty full", "decently filled"}:
        return None, "Decently filled"
    if normalized == "mostly full":
        return None, "Mostly full"
    if normalized == "full":
        return None, "Full"
    if normalized in {"almost empty", "nearly empty"}:
        return None, "Almost empty"
    if normalized in {"low", "running low"}:
        return None, "Low"
    return None, None


def _qualitative_review_reason() -> str:
    return "Qualitative fullness quantity; confirm the exact count before export."


def _candidate_from_fullness(
    *,
    raw_phrase: str,
    item_name: str,
    unit: str,
    fullness: str,
    needed_quantity: str,
) -> ParsedCandidate:
    quantity, quantity_label = _normalize_fullness(fullness)
    is_qualitative = quantity_label is not None
    return ParsedCandidate(
        raw_phrase=raw_phrase,
        quantity=quantity,
        unit=unit,
        item_name=item_name,
        partial_detail=fullness if quantity is not None else None,
        needs_review=is_qualitative,
        review_reason=_qualitative_review_reason() if is_qualitative else None,
        status="Needs Review" if is_qualitative else "Partial Quantity",
        needed_quantity=needed_quantity,
        quantity_label=quantity_label,
    )


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


def _parse_container_fullness_phrases(text: str) -> list[ParsedCandidate]:
    source = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    matches = list(CONTAINER_START_PATTERN.finditer(source))
    candidates: list[ParsedCandidate] = []
    for index, match in enumerate(matches):
        if match.group("amount").lower() in {"one", "1"}:
            # The normal numeric path handles "one tub of ranch half full".
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        sentence_end = re.search(r"[.;]", source[match.end() : next_start])
        end = match.end() + sentence_end.start() if sentence_end else next_start
        raw_phrase = source[match.start() : end].strip(" ,.")
        remainder = source[match.end() : end].strip(" ,.")
        if not remainder:
            continue

        needed_quantity = _extract_needed_quantity(raw_phrase, _container_unit(match.group("container")))
        remainder_without_needed = _remove_needed_quantity_clause(remainder)
        fullness_match = FULLNESS_PATTERN.search(remainder_without_needed)
        if not fullness_match:
            continue

        item_name = _clean_item_name(remainder_without_needed[: fullness_match.start()])
        if not item_name or UNUSABLE_ITEM_PATTERN.search(item_name):
            continue
        candidates.append(
            _candidate_from_fullness(
                raw_phrase=raw_phrase,
                item_name=item_name,
                unit=_container_unit(match.group("container")),
                fullness=fullness_match.group("fullness"),
                needed_quantity=needed_quantity,
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
        needed_quantity = _extract_needed_quantity(phrase, unit)
        item_part = _remove_needed_quantity_clause(item_part)
        fullness_match = FULLNESS_PATTERN.search(item_part)
        multi_container_partial = bool(
            fullness_match
            and re.search(r"\bone\s+(?:of\s+)?(?:which|them|the\s+\w+)\b", item_part[: fullness_match.end()], re.IGNORECASE)
        )
        if fullness_match and not multi_container_partial:
            item_name = _clean_item_name(item_part[: fullness_match.start()])
            if not item_name:
                continue
            first_word = match.group("first")
            fullness_unit = _container_unit(first_word) if first_word.lower() in CONTAINER_UNITS else unit
            candidates.append(
                _candidate_from_fullness(
                    raw_phrase=phrase,
                    item_name=item_name,
                    unit=fullness_unit,
                    fullness=fullness_match.group("fullness"),
                    needed_quantity=needed_quantity,
                )
            )
            continue
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
                needed_quantity=needed_quantity,
            )
        )
    candidates.extend(_parse_container_fullness_phrases(text))
    candidates.extend(_parse_vague_quantity_phrases(text))
    return candidates
