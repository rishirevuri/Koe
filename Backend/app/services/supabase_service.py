from app.config import get_settings


def get_supabase_status() -> dict[str, bool | str]:
    settings = get_settings()
    return {
        "configured": settings.is_supabase_configured,
        "provider": "supabase",
        "url_present": settings._has_real_value(settings.supabase_url),
        "anon_key_present": settings._has_real_value(settings.supabase_anon_key),
        "service_role_key_present": settings._has_real_value(settings.supabase_service_role_key),
        "message": "Supabase credentials are present but no connection is made yet."
        if settings.is_supabase_configured
        else "Supabase is not configured yet. Add SUPABASE_URL and a Supabase key when ready.",
    }
