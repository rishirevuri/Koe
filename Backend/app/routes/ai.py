from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CountEntry, CountSession
from app.schemas import MatchResponse, NormalizeItemRequest, ParseResponse, ParseUploadRequest, ParseVoiceRequest, ParsedEntry
from app.services.issue_service import create_issue
from app.services.matching_service import MatchResult, match_inventory_item
from app.services.upload_parse_service import parse_upload_text
from app.services.voice_parse_service import ParsedCandidate, parse_voice_text


router = APIRouter(prefix="/ai", tags=["ai"])


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
) -> ParseResponse:
    count = db.get(CountSession, count_session_id)
    if not count or count.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="Count session not found for restaurant")

    parsed: list[ParsedEntry] = []
    for candidate in candidates:
        match = match_inventory_item(db, restaurant_id, candidate.item_name)
        needs_review = candidate.needs_review or match.needs_review
        review_reason = candidate.review_reason or match.review_reason
        entry_id: int | None = None
        entry = None
        clean_name = match.matched_name or candidate.item_name
        if save:
            entry = CountEntry(
                count_session_id=count_session_id,
                inventory_item_id=match.matched_item_id,
                item_name=clean_name,
                normalized_item_name=match.normalized_name,
                quantity=candidate.quantity,
                unit=candidate.unit,
                area=area or count.area,
                source=source,
                raw_input=text,
                partial_detail=candidate.partial_detail,
                needs_review=needs_review,
                review_reason=review_reason,
            )
            db.add(entry)
            db.flush()
            entry_id = entry.id

        issue_type = _issue_type(match, candidate)
        if issue_type:
            create_issue(
                db,
                restaurant_id=restaurant_id,
                count_session_id=count_session_id,
                inventory_item_id=match.matched_item_id,
                count_entry_id=entry_id,
                issue_type=issue_type,
                title=review_reason or "Inventory count needs review",
                description=f"Parsed phrase '{candidate.raw_phrase}' needs review.",
                suggested_action="Confirm the item, unit, or partial quantity before approval.",
            )

        parsed.append(
            ParsedEntry(
                raw_phrase=candidate.raw_phrase,
                item_name=clean_name,
                normalized_item_name=match.normalized_name,
                quantity=candidate.quantity,
                unit=candidate.unit,
                area=area or count.area,
                source=source,
                raw_input=text,
                partial_detail=candidate.partial_detail,
                inventory_item_id=match.matched_item_id,
                matched_name=match.matched_name,
                match_type=match.match_type,
                needs_review=needs_review,
                review_reason=review_reason,
                count_entry_id=entry_id,
            )
        )

    if save:
        db.commit()
    return ParseResponse(entries=parsed, saved=save)


@router.post("/parse-voice", response_model=ParseResponse)
def parse_voice(payload: ParseVoiceRequest, db: Session = Depends(get_db)) -> ParseResponse:
    return _handle_candidates(
        db,
        restaurant_id=payload.restaurant_id,
        count_session_id=payload.count_session_id,
        text=payload.text,
        area=payload.area,
        source="voice",
        save=payload.save,
        candidates=parse_voice_text(payload.text),
    )


@router.post("/parse-upload", response_model=ParseResponse)
def parse_upload(payload: ParseUploadRequest, db: Session = Depends(get_db)) -> ParseResponse:
    return _handle_candidates(
        db,
        restaurant_id=payload.restaurant_id,
        count_session_id=payload.count_session_id,
        text=payload.text,
        area=payload.area,
        source="upload",
        save=payload.save,
        candidates=parse_upload_text(payload.text),
    )


@router.post("/normalize-item", response_model=MatchResponse)
def normalize_item(payload: NormalizeItemRequest, db: Session = Depends(get_db)) -> MatchResult:
    return match_inventory_item(db, payload.restaurant_id, payload.item_name)
