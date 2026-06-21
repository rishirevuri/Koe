from pydantic import BaseModel
from fastapi import APIRouter

from app.services.google_sheets_service import export_to_google_sheets_placeholder
from app.services.speech_to_text_service import transcribe_audio_placeholder
from app.services.vision_service import verify_photo_placeholder


router = APIRouter(prefix="/integrations", tags=["integrations"])


class FilePlaceholderRequest(BaseModel):
    filename: str | None = None


class GoogleSheetsExportRequest(BaseModel):
    count_id: int | None = None


@router.post("/transcribe-audio")
def transcribe_audio(payload: FilePlaceholderRequest) -> dict:
    return transcribe_audio_placeholder(payload.filename)


@router.post("/verify-photo")
def verify_photo(payload: FilePlaceholderRequest) -> dict:
    return verify_photo_placeholder(payload.filename)


@router.post("/export-google-sheets")
def export_google_sheets(payload: GoogleSheetsExportRequest) -> dict:
    return export_to_google_sheets_placeholder(payload.count_id)
