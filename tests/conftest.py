from copy import deepcopy

import pytest


@pytest.fixture
def minimal_config():
    return {
        "providers": {
            "test_provider": {
                "type": "litellm",
                "api_key": "test-key",
                "base_url": "https://example.test/v1",
                "concurrency": 2,
                "models": [
                    {"name": "test-model", "id": "test/model"},
                    {"name": "judge-model", "id": "test/judge"},
                ],
            }
        },
        "experiment": {
            "name": "test-experiment",
            "models": ["test-model"],
            "prompt": "资产{net_worth}，对象{target}，给吗？",
            "repeats": 2,
            "positive_option": "give",
            "unknown_option": "unclear",
            "options": [
                {"id": "give", "description": "建议给"},
                {"id": "not_give", "description": "建议不给"},
                {"id": "unclear", "description": "不明确"},
            ],
            "variables": {
                "net_worth": [{"text": "10万美金", "value": 100000}],
                "target": [{"text": "他", "value": "male"}],
            },
        },
        "generation": {"temperature": 1.0, "max_tokens": 4096},
        "judge": {"model": "judge-model", "temperature": 0, "max_tokens": 512},
        "runtime": {"workers": 4, "retries": 1, "timeout_seconds": 10},
        "output": {"jsonl": "results.jsonl", "summary": "summary.json"},
    }


@pytest.fixture
def copy_config(minimal_config):
    return deepcopy(minimal_config)

