import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CountEntry, CountSession
from app.schemas import MatchResponse, NormalizeItemRequest, ParseResponse, ParseUploadRequest, ParseVoiceRequest, ParsedEntry
from app.config import get_settings
from app.auth import SupabaseUser, ensure_restaurant_id_matches, get_current_restaurant, get_current_supabase_user
from app.services.issue_service import create_issue
from app.services.matching_service import MatchResult, match_inventory_item
from app.services.external_ai_service import parse_inventory_with_claude
from app.services.upload_parse_service import parse_upload_text
from app.services.voice_parse_service import ParsedCandidate, parse_voice_text


router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)
INVALID_FALLBACK_ITEM_NAMES = {
    "of",
    "and",
    "then",
    "packs of",
    "cases of",
    "bunches wait no scratch that",
    "is half empty",
    "more on the bottom shelf",
}


def _has_anthropic_key(settings) -> bool:
    checker = getattr(settings, "_has_real_value", None)
    if callable(checker):
        return bool(checker(getattr(settings, "anthropic_api_key", None)))
    value = getattr(settings, "anthropic_api_key", None)
    return bool(value and str(value).strip() and not str(value).strip().startswith("your_"))


def _parser_debug(settings, parser_source: str) -> dict:
    return {
        "parser_source": parser_source,
        "external_ai_enabled": bool(getattr(settings, "enable_external_ai", False)),
        "text_ai_provider": getattr(settings, "text_ai_provider", None) or "",
        "anthropic_model": getattr(settings, "anthropic_model", None) or "",
        "anthropic_key_present": _has_anthropic_key(settings),
    }


def _is_invalid_fallback_candidate(candidate: ParsedCandidate) -> bool:
    name = " ".join(candidate.item_name.lower().strip(" ,.").split())
    return name in INVALID_FALLBACK_ITEM_NAMES


def _status_for_candidate(candidate: ParsedCandidate, match: MatchResult, parser_source: str | None = None) -> str:
    if parser_source == "claude" and candidate.status in {"Clean", "Partial Quantity", "Missing Unit", "Possible Duplicate", "Converted Unit"}:
        return candidate.status
    if candidate.needs_review or match.needs_review:
        return "Needs Review"
    if candidate.status in {"Clean", "Partial Quantity", "Missing Unit", "Possible Duplicate", "Converted Unit"}:
        return candidate.status
    if not candidate.unit:
        return "Missing Unit"
    if candidate.partial_detail:
        return "Partial Quantity"
    return "Clean"


def _issue_type(match: MatchResult, candidate: ParsedCandidate) -> str | None:
    if candidate.needs_review and candidate.review_reason and "Vague partial" in candidate.review_reason:
        return "vague_partial_quantity"
    if match.match_type == "none":
        return "unknown_item"
    if match.needs_review:
        return "low_confidence_match"
    return None


def _handle_candidates(
    db: Session,
    *,
    restaurant_id: int,
    count_session_id: int,
    text: str,
    area: str | None,
    source: str,
    save: bool,
    candidates: list[ParsedCandidate],
    counted_by: str | None,
    parser_debug: dict | None = None,
) -> ParseResponse:
    count = db.get(CountSession, count_session_id)
    if not count or count.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="Count session not found for restaurant")

    parser_source = (parser_debug or {}).get("parser_source")
    parsed: list[ParsedEntry] = []
    for candidate in candidates:
        if parser_source == "deterministic_fallback" and _is_invalid_fallback_candidate(candidate):
            logger.info("parse_voice: dropped invalid deterministic_fallback row name=%s", candidate.item_name)
            continue
        match = match_inventory_item(db, restaurant_id, candidate.item_name)
        needs_review = candidate.needs_review or match.needs_review
        review_reason = candidate.review_reason or match.review_reason
        entry = None
        created_at = None
        clean_name = match.matched_name or candidate.item_name
        status = _status_for_candidate(candidate, match, parser_source)
        if save:
            entry = CountEntry(
                count_session_id=count_session_id,
                inventory_item_id=match.matched_item_id,
                item_name_raw=candidate.item_name,
                item_name=clean_name,
                normalized_item_name=match.normalized_name,
                quantity=candidate.quantity,
                unit=candidate.unit,
                status=status,
                area=area or count.area,
                source=source,
                raw_input=text,
                original_phrase=candidate.raw_phrase,
                partial_detail=candidate.partial_detail,
                needs_review=needs_review,
                review_reason=review_reason,
                counted_by=counted_by,
            )
            db.add(entry)
            db.flush()
            created_at = entry.created_at

        issue_type = _issue_type(match, candidate)
        if issue_type:
            create_issue(
                db,
                restaurant_id=restaurant_id,
                count_session_id=count_session_id,
                inventory_item_id=match.matched_item_id,
                count_entry_id=entry.id if entry else None,
                issue_type=issue_type,
                title=review_reason or "Inventory count needs review",
                description=f"Parsed phrase '{candidate.raw_phrase}' needs review.",
                suggested_action="Confirm the item, unit, or partial quantity before approval.",
            )

        parsed.append(
            ParsedEntry(
                count_id=count_session_id,
                restaurant_id=restaurant_id,
                quantity=candidate.quantity,
                unit=candidate.unit,
                area=area or count.area,
                item_name_raw=candidate.item_name,
                item_name_clean=clean_name,
                status=status,
                original_phrase=candidate.raw_phrase,
                created_at=created_at,
                counted_by=counted_by,
            )
        )

    if save:
        db.commit()
    return ParseResponse(entries=parsed, saved=save, **(parser_debug or {}))


@router.post("/parse-voice", response_model=ParseResponse)
def parse_voice(
    payload: ParseVoiceRequest,
    db: Session = Depends(get_db),
    current_restaurant=Depends(get_current_restaurant),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> ParseResponse:
    ensure_restaurant_id_matches(payload.restaurant_id, current_restaurant)
    settings = get_settings()
    provider = settings.text_ai_provider or "claude"
    model = getattr(settings, "anthropic_model", "") or ""
    anthropic_key_present = _has_anthropic_key(settings)
    parser_source = "deterministic_fallback"

    logger.info(
        "parse_voice: external_ai_enabled=%s provider=%s anthropic_key_present=%s model=%s",
        settings.enable_external_ai,
        provider,
        anthropic_key_present,
        model,
    )

    candidates = parse_voice_text(payload.text)
    if settings.enable_external_ai and settings.is_claude_configured and (settings.text_ai_provider or "claude").lower() == "claude":
        try:
            logger.info("parse_voice: attempting Claude parse")
            claude_candidates = parse_inventory_with_claude(payload.text)
            candidates = claude_candidates
            parser_source = "claude"
            logger.info("parse_voice: Claude parse succeeded")
        except Exception as error:
            logger.warning(
                "parse_voice: Claude parse failed; using deterministic_fallback; error_type=%s; model=%s",
                type(error).__name__,
                model,
            )
            candidates = parse_voice_text(payload.text)
    logger.info("parse_voice: using parser_source=%s", parser_source)

    return _handle_candidates(
        db,
        restaurant_id=current_restaurant.id,
        count_session_id=payload.count_session_id,
        text=payload.text,
        area=payload.area,
        source="voice",
        save=payload.save,
        candidates=candidates,
        counted_by=current_user.email or current_user.user_id,
        parser_debug=_parser_debug(settings, parser_source),
    )


@router.post("/parse-upload", response_model=ParseResponse)
def parse_upload(
    payload: ParseUploadRequest,
    db: Session = Depends(get_db),
    current_restaurant=Depends(get_current_restaurant),
    current_user: SupabaseUser = Depends(get_current_supabase_user),
) -> ParseResponse:
    ensure_restaurant_id_matches(payload.restaurant_id, current_restaurant)
    return _handle_candidates(
        db,
        restaurant_id=current_restaurant.id,
        count_session_id=payload.count_session_id,
        text=payload.text,
        area=payload.area,
        source="upload",
        save=payload.save,
        candidates=parse_upload_text(payload.text),
        counted_by=current_user.email or current_user.user_id,
    )


@router.post("/normalize-item", response_model=MatchResponse)
def normalize_item(
    payload: NormalizeItemRequest,
    db: Session = Depends(get_db),
    current_restaurant=Depends(get_current_restaurant),
) -> MatchResult:
    ensure_restaurant_id_matches(payload.restaurant_id, current_restaurant)
    return match_inventory_item(db, current_restaurant.id, payload.item_name)
