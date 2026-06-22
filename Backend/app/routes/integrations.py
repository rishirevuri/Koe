from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.services.external_ai_service import parse_inventory_with_claude_placeholder
from app.services.google_sheets_service import export_report_to_google_sheets_placeholder
from app.services.speech_to_text_service import transcribe_audio_placeholder


router = APIRouter(prefix="/integrations", tags=["integrations"])


class FilePlaceholderRequest(BaseModel):
    filename: str | None = None


class ClaudeParseRequest(BaseModel):
    transcript: str


class GoogleSheetsExportRequest(BaseModel):
    count_id: int | None = None


@router.get("/status")
def integrations_status() -> dict[str, bool]:
    settings = get_settings()
    return {
        "external_ai_enabled": settings.enable_external_ai,
        "supabase_configured": settings.is_supabase_configured,
        "elevenlabs_configured": settings.is_elevenlabs_configured,
        "gemini_configured": settings.is_gemini_configured,
        "claude_configured": settings.is_claude_configured,
        "google_sheets_configured": settings.is_google_sheets_configured,
        "payments_enabled": settings.payments_enabled,
    }


@router.post("/transcribe-audio")
def transcribe_audio(payload: FilePlaceholderRequest) -> dict:
    return transcribe_audio_placeholder(payload.filename)


@router.post("/parse-with-claude")
def parse_with_claude(payload: ClaudeParseRequest) -> dict:
    return parse_inventory_with_claude_placeholder(payload.transcript)


@router.post("/export-google-sheets")
def export_google_sheets(payload: GoogleSheetsExportRequest) -> dict:
    return export_report_to_google_sheets_placeholder(payload.count_id)
