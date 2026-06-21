import re
import string


PHRASE_NORMALIZATIONS = {
    "extra virgin olive oil": "extra virgin olive oil",
    "e v o o": "evoo",
}


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(value: str) -> str:
    cleaned = value.lower().replace("&", " and ")
    cleaned = cleaned.translate(str.maketrans("", "", string.punctuation.replace("-", "")))
    cleaned = collapse_whitespace(cleaned.replace("-", " "))
    return PHRASE_NORMALIZATIONS.get(cleaned, cleaned)


def simple_singular(value: str) -> str:
    if len(value) > 3 and value.endswith("ies"):
        return f"{value[:-3]}y"
    if len(value) > 4 and value.endswith("oes"):
        return value[:-2]
    if len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value
