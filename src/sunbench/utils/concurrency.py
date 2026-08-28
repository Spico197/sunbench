import asyncio
from typing import Any, Dict, Mapping


class ProviderLimiters:
    def __init__(self, providers: Mapping[str, Mapping[str, Any]]):
        self._semaphores: Dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(int(provider.get("concurrency", 1)))
            for name, provider in providers.items()
        }

    def get(self, provider_name: str) -> asyncio.Semaphore:
        return self._semaphores[provider_name]

