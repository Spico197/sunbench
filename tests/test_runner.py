import asyncio
import json
from copy import deepcopy

import yaml

from sunbench import runner
from sunbench.runner import build_summary, build_tasks


def test_builds_full_5_by_5_by_3_by_5_grid(copy_config):
    copy_config["experiment"]["repeats"] = 5
    copy_config["experiment"]["prompt"] = "{a}-{b}-{c}"
    copy_config["experiment"]["variables"] = {
        "a": [{"text": str(i), "value": i} for i in range(5)],
        "b": [{"text": str(i), "value": i} for i in range(5)],
        "c": [{"text": str(i), "value": i} for i in range(3)],
    }

    tasks = build_tasks(copy_config)

    assert len(tasks) == 375
    assert len({task["task_id"] for task in tasks}) == 375
    assert tasks[0]["prompt"] == "0-0-0"


def test_run_writes_results_summary_and_resumes(
    tmp_path, monkeypatch, capsys, copy_config
):
    copy_config["providers"]["test_provider"]["api_key"] = "${TEST_RUN_KEY}"
    copy_config["providers"]["test_provider"]["concurrency"] = 1
    copy_config["runtime"]["progress_interval_seconds"] = 0.002
    copy_config["output"] = {
        "jsonl": "runs/results.jsonl",
        "summary": "runs/summary.json",
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(copy_config, allow_unicode=True), encoding="utf-8"
    )
    (tmp_path / ".env").write_text("TEST_RUN_KEY=secret\n", encoding="utf-8")

    calls = []
    active = 0
    max_active = 0

    async def fake_completion(provider, model_id, messages, generation):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        calls.append((model_id, deepcopy(messages), deepcopy(generation)))
        active -= 1
        if model_id == "test/judge":
            content = '{"option":"give","reason":"明确建议给"}'
            reasoning = None
        else:
            content = "给"
            reasoning = "内部推理"
        return {
            "raw": {"id": len(calls), "model": model_id},
            "content": content,
            "reasoning_content": reasoning,
            "usage": {"total_tokens": 3},
            "model": model_id,
        }

    monkeypatch.setattr(runner.registry, "get_provider_completion", lambda _: fake_completion)

    first = asyncio.run(runner.run(config_path))
    first_call_count = len(calls)
    second = asyncio.run(runner.run(config_path))
    log_lines = capsys.readouterr().out.splitlines()

    assert first_call_count == 4
    assert len(calls) == first_call_count
    assert max_active == 1
    assert first["overall"]["positive_probability"] == 1.0
    assert second["overall"]["completed_count"] == 2

    jsonl_path = tmp_path / "runs" / "results.jsonl"
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert len(records) == 2
    assert all(record["status"] == "complete" for record in records)
    assert all(record["generation"]["response"]["raw"] for record in records)
    assert all(
        record["generation"]["response"]["reasoning_content"] == "内部推理"
        for record in records
    )
    assert all(record["judge"]["response"]["raw"] for record in records)
    assert all(record["normalized_option"] == "give" for record in records)

    saved_summary = json.loads(
        (tmp_path / "runs" / "summary.json").read_text(encoding="utf-8")
    )
    assert saved_summary["overall"]["valid_count"] == 2
    start_lines = [line for line in log_lines if line.startswith("[start]")]
    progress_lines = [line for line in log_lines if line.startswith("[progress]")]
    done_lines = [line for line in log_lines if line.startswith("[done]")]
    assert start_lines
    assert "providers=1 models=1" in start_lines[0]
    assert "variables=net_worth:1,target:1" in start_lines[0]
    assert "scenarios=1 model_conditions=1 repeats=2 tasks=2" in start_lines[0]
    assert progress_lines
    assert all(
        "providers=1 models=1 variables=net_worth:1,target:1" in line
        and "elapsed=" in line
        and "eta=" in line
        for line in progress_lines
    )
    assert done_lines
    assert "elapsed=" in done_lines[0]
    assert "speed=" in done_lines[0]
    assert "eta=00:00:00" in done_lines[0]
    assert "api_gen=2 api_judge=2 api_total=4" in done_lines[0]


def test_failed_task_is_retried_on_next_run(tmp_path, monkeypatch, copy_config):
    copy_config["output"] = {
        "jsonl": "results.jsonl",
        "summary": "summary.json",
    }
    copy_config["experiment"]["repeats"] = 1
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(copy_config, allow_unicode=True), encoding="utf-8"
    )
    generation_calls = 0

    async def flaky_completion(provider, model_id, messages, generation):
        nonlocal generation_calls
        if model_id == "test/model":
            generation_calls += 1
            if generation_calls == 1:
                raise TimeoutError("temporary timeout")
            content = "给"
        else:
            content = '{"option":"give","reason":"明确"}'
        return {
            "raw": {"model": model_id},
            "content": content,
            "reasoning_content": None,
            "usage": None,
            "model": model_id,
        }

    monkeypatch.setattr(runner.registry, "get_provider_completion", lambda _: flaky_completion)

    first = asyncio.run(runner.run(config_path))
    second = asyncio.run(runner.run(config_path))

    assert first["overall"]["generation_error_count"] == 1
    assert second["overall"]["completed_count"] == 1
    assert generation_calls == 2
    records = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["status"] for record in records] == ["generation_error", "complete"]


def test_summary_excludes_unknown_and_errors_from_probability(copy_config):
    tasks = build_tasks(copy_config)
    records = [
        {"task_id": tasks[0]["task_id"], "status": "complete", "normalized_option": "give"},
        {"task_id": tasks[1]["task_id"], "status": "complete", "normalized_option": "unclear"},
    ]

    summary = build_summary(copy_config, tasks, records)

    assert summary["overall"]["positive_probability"] == 1.0
    assert summary["overall"]["valid_count"] == 1
    assert summary["overall"]["unknown_count"] == 1
