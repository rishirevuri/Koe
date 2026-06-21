from app.config import get_settings
from app.services.external_ai_service import external_ai_disabled_response


def export_to_google_sheets_placeholder(count_id: int | None = None) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai or not settings.google_api_key:
        return external_ai_disabled_response()
    return {
        "configured": True,
        "message": "Google Sheets export is configured but not implemented yet.",
        "count_id": count_id,
    }
