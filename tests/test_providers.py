import asyncio
from types import SimpleNamespace

from sunbench.providers import litellm as litellm_provider
from sunbench.providers import openai_compatible


def test_litellm_provider_forwards_generation_and_extracts_reasoning(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {
            "model": "resolved-model",
            "choices": [
                {
                    "message": {
                        "content": "给",
                        "reasoning_content": "reasoning",
                    }
                }
            ],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(litellm_provider, "acompletion", fake_acompletion)
    result = asyncio.run(
        litellm_provider.completion(
            {
                "api_key": "key",
                "base_url": "https://example.test/v1",
                "timeout_seconds": 30,
            },
            "openrouter/test/model",
            [{"role": "user", "content": "question"}],
            {"temperature": 1.0, "max_tokens": 4096},
        )
    )

    assert captured["max_tokens"] == 4096
    assert captured["api_base"] == "https://example.test/v1"
    assert result["content"] == "给"
    assert result["reasoning_content"] == "reasoning"


def test_openai_compatible_provider_extracts_full_response(monkeypatch):
    class Dumpable(SimpleNamespace):
        def model_dump(self, mode="json"):
            return dict(self.__dict__)

    message = Dumpable(content="不给", reasoning_content="reasoning")
    usage = Dumpable(total_tokens=5)
    response = Dumpable(
        choices=[Dumpable(message=message)], usage=usage, model="custom-model"
    )
    response.model_dump = lambda mode="json": {
        "choices": [{"message": message.model_dump()}],
        "usage": usage.model_dump(),
        "model": "custom-model",
    }
    captured = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return response

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    monkeypatch.setattr(openai_compatible, "_client", lambda _: fake_client)

    result = asyncio.run(
        openai_compatible.completion(
            {
                "api_key": "key",
                "base_url": "https://example.test/v1",
                "timeout_seconds": 30,
            },
            "custom-model",
            [{"role": "user", "content": "question"}],
            {"max_tokens": 4096},
        )
    )

    assert captured["max_tokens"] == 4096
    assert result["content"] == "不给"
    assert result["reasoning_content"] == "reasoning"
