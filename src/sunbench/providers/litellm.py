from typing import Any, Dict, List

from litellm import acompletion


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


async def completion(
    provider: Dict[str, Any],
    model_id: str,
    messages: List[Dict[str, str]],
    generation: Dict[str, Any],
) -> Dict[str, Any]:
    response = await acompletion(
        model=model_id,
        messages=messages,
        api_key=provider["api_key"],
        api_base=provider["base_url"],
        timeout=provider.get("timeout_seconds"),
        drop_params=True,
        **generation,
    )
    choice = _field(response, "choices", [])[0]
    message = _field(choice, "message", {})
    provider_fields = _field(message, "provider_specific_fields", {}) or {}
    reasoning = _field(message, "reasoning_content") or _field(message, "reasoning")
    if reasoning is None and isinstance(provider_fields, dict):
        reasoning = provider_fields.get("reasoning_content") or provider_fields.get(
            "reasoning"
        )
    return {
        "raw": _dump(response),
        "content": _field(message, "content"),
        "reasoning_content": reasoning,
        "usage": _dump(_field(response, "usage")),
        "model": _field(response, "model", model_id),
    }
