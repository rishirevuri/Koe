from app.config import get_settings
from app.services.external_ai_service import external_ai_disabled_response


def transcribe_audio_placeholder(filename: str | None = None) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai or not settings.openai_api_key:
        return external_ai_disabled_response()
    return {
        "configured": True,
        "message": "Speech-to-text is configured but not implemented yet.",
        "filename": filename,
    }
