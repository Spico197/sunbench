from importlib import import_module
from typing import Any, Awaitable, Callable, Dict, List


CompletionFunction = Callable[
    [Dict[str, Any], str, List[Dict[str, str]], Dict[str, Any]],
    Awaitable[Dict[str, Any]],
]

PROVIDER_MODULES = {
    "litellm": "sunbench.providers.litellm",
    "openai_compatible": "sunbench.providers.openai_compatible",
}


def get_provider_completion(provider_type: str) -> CompletionFunction:
    module_name = PROVIDER_MODULES.get(provider_type)
    if module_name is None:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    module = import_module(module_name)
    return module.completion

