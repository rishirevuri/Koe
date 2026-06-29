import re
from dataclasses import dataclass

from app.utils.units import normalize_unit


@dataclass
class PartialQuantityResult:
    quantity: float | None
    unit: str | None
    partial_detail: str | None
    needs_review: bool
    review_reason: str | None


FRACTIONS = {
    "half": 0.5,
    "quarter": 0.25,
    "fourth": 0.25,
    "three quarters": 0.75,
    "three fourths": 0.75,
}
VAGUE_PARTIALS = ("almost empty", "mostly full", "partially full", "partial", "some left")


def _detail(full_count: int, unit: str, label: str) -> str:
    singular = unit[:-1] if unit.endswith("s") else unit
    return f"{full_count} full {unit} + 1 {label} {singular}"


def parse_partial_quantity(phrase: str, quantity: float | None = None, unit: str | None = None) -> PartialQuantityResult:
    text = phrase.lower()
    normalized_unit = normalize_unit(unit) if unit else None

    plus_match = re.search(
        r"(?P<whole>\d+(?:\.\d+)?)\s+(?P<unit>[a-z]+)\s+(?:plus|and)\s+half\s+a?\s*(?P=unit)?",
        text,
    )
    if plus_match:
        whole = float(plus_match.group("whole"))
        parsed_unit = normalize_unit(plus_match.group("unit"))
        return PartialQuantityResult(
            quantity=whole + 0.5,
            unit=parsed_unit,
            partial_detail=f"{int(whole) if whole.is_integer() else whole} full {parsed_unit} + 1 half {parsed_unit[:-1] if parsed_unit.endswith('s') else parsed_unit}",
            needs_review=False,
            review_reason=None,
        )

    for vague in VAGUE_PARTIALS:
        if vague in text:
            return PartialQuantityResult(
                quantity=quantity,
                unit=normalized_unit,
                partial_detail=None,
                needs_review=True,
                review_reason=f"Vague partial quantity: {vague}",
            )

    if quantity is None or normalized_unit is None:
        return PartialQuantityResult(quantity=quantity, unit=normalized_unit, partial_detail=None, needs_review=False, review_reason=None)

    fraction_label: str | None = None
    fraction_value: float | None = None
    for label, value in FRACTIONS.items():
        if re.search(
            rf"\bone\s+(?:(?:of\s+)?(?:which|them)\s+)?(?:is\s+)?{re.escape(label)}\s+(?:empty|full)?\b",
            text,
        ):
            fraction_label = label
            fraction_value = value
            break

    if fraction_label is None or fraction_value is None:
        return PartialQuantityResult(quantity=quantity, unit=normalized_unit, partial_detail=None, needs_review=False, review_reason=None)

    whole = max(int(quantity) - 1, 0)
    return PartialQuantityResult(
        quantity=whole + fraction_value,
        unit=normalized_unit,
        partial_detail=_detail(whole, normalized_unit, fraction_label),
        needs_review=False,
        review_reason=None,
    )
