from app.config import get_settings


def transcribe_audio_placeholder(filename: str | None = None) -> dict:
    settings = get_settings()
    provider = settings.speech_provider or "elevenlabs"
    if not settings.enable_external_ai or not settings.is_elevenlabs_configured:
        return {
            "configured": False,
            "provider": provider,
            "message": "Speech-to-text is not configured yet. Add ELEVENLABS_API_KEY and set ENABLE_EXTERNAL_AI=true.",
        }
    return {
        "configured": True,
        "provider": provider,
        "message": "Speech-to-text is configured but not implemented yet.",
        "filename": filename,
    }
