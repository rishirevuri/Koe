from app.config import get_settings


def external_ai_disabled_response() -> dict[str, bool | str]:
    return {
        "configured": False,
        "message": "External AI integrations are disabled. Add API keys and set ENABLE_EXTERNAL_AI=true to enable this route.",
    }


def parse_inventory_with_llm_placeholder(text: str) -> dict:
    settings = get_settings()
    if not settings.enable_external_ai or not settings.openai_api_key:
        return external_ai_disabled_response()
    return {
        "configured": True,
        "message": "LLM inventory parsing is configured but not implemented yet.",
        "input_preview": text[:120],
    }
