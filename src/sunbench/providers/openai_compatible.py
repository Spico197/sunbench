from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI


_CLIENTS: Dict[Tuple[str, str, int], AsyncOpenAI] = {}


def _client(provider: Dict[str, Any]) -> AsyncOpenAI:
    timeout = int(provider.get("timeout_seconds", 180))
    key = (provider["base_url"], provider["api_key"], timeout)
    if key not in _CLIENTS:
        _CLIENTS[key] = AsyncOpenAI(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            timeout=timeout,
        )
    return _CLIENTS[key]


async def completion(
    provider: Dict[str, Any],
    model_id: str,
    messages: List[Dict[str, str]],
    generation: Dict[str, Any],
) -> Dict[str, Any]:
    response = await _client(provider).chat.completions.create(
        model=model_id,
        messages=messages,
        **generation,
    )
    raw = response.model_dump(mode="json")
    message = response.choices[0].message
    message_raw = message.model_dump(mode="json")
    reasoning = message_raw.get("reasoning_content") or message_raw.get("reasoning")
    return {
        "raw": raw,
        "content": message.content,
        "reasoning_content": reasoning,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "model": response.model,
    }

