from app.config import get_settings


def verify_photo_placeholder(filename: str | None = None) -> dict:
    settings = get_settings()
    provider = settings.text_ai_provider or "claude"
    if not settings.enable_external_ai or not settings.is_claude_configured:
        return {
            "configured": False,
            "provider": provider,
            "message": "Photo verification is not configured yet. Add ANTHROPIC_API_KEY and set ENABLE_EXTERNAL_AI=true.",
        }
    return {
        "configured": True,
        "provider": provider,
        "message": "Photo verification is configured but not implemented yet.",
        "filename": filename,
    }
