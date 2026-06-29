from app.config import get_settings


def export_report_to_google_sheets_placeholder(count_id: int | None = None) -> dict:
    settings = get_settings()
    provider = "google_sheets"
    if not settings.enable_external_ai or not settings.is_google_sheets_configured:
        return {
            "configured": False,
            "provider": provider,
            "message": "Google Sheets export is not configured yet. Add Google Sheets OAuth credentials and set ENABLE_EXTERNAL_AI=true.",
        }
    return {
        "configured": True,
        "provider": provider,
        "message": "Google Sheets export is configured but not implemented yet.",
        "count_id": count_id,
    }


def export_to_google_sheets_placeholder(count_id: int | None = None) -> dict:
    return export_report_to_google_sheets_placeholder(count_id)
