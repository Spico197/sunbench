import asyncio
import hashlib
import itertools
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sunbench.config import build_model_index, load_config
from sunbench.judge import JudgeParseError, build_judge_messages, parse_judge_response
from sunbench.utils import registry
from sunbench.utils.concurrency import ProviderLimiters
from sunbench.utils.jsonl import JsonlWriter, read_jsonl, write_json_atomic
from sunbench.utils.retry import RetryExhausted, utc_now, with_retry


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _attempt_count(record: Mapping[str, Any], stage: str) -> int:
    stage_record = record.get(stage)
    if not isinstance(stage_record, dict):
        return 0
    attempts = stage_record.get("attempts")
    return len(attempts) if isinstance(attempts, list) else 0


def _stable_id(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def build_tasks(config: Mapping[str, Any]) -> List[Dict[str, Any]]:
    experiment = config["experiment"]
    model_index = build_model_index(config)
    judge_ref = model_index[config["judge"]["model"]]
    variable_names = list(experiment["variables"])
    variable_values = [experiment["variables"][name] for name in variable_names]
    tasks: List[Dict[str, Any]] = []

    for model_alias in experiment["models"]:
        model_ref = model_index[model_alias]
        for combination in itertools.product(*variable_values):
            variables = {
                name: dict(item) for name, item in zip(variable_names, combination)
            }
            rendered = {
                name: str(item["text"]) for name, item in variables.items()
            }
            prompt = experiment["prompt"].format(**rendered)
            for repeat_index in range(1, int(experiment["repeats"]) + 1):
                identity = {
                    "experiment": experiment["name"],
                    "model": model_alias,
                    "provider": model_ref["provider_name"],
                    "model_id": model_ref["id"],
                    "variables": variables,
                    "repeat_index": repeat_index,
                    "prompt": prompt,
                    "generation": config["generation"],
                    "judge_model": config["judge"]["model"],
                    "judge_provider": judge_ref["provider_name"],
                    "judge_model_id": judge_ref["id"],
                    "judge_generation": {
                        key: value
                        for key, value in config["judge"].items()
                        if key != "model"
                    },
                    "options": experiment["options"],
                }
                tasks.append(
                    {
                        "task_id": _stable_id(identity),
                        "model": model_alias,
                        "model_ref": model_ref,
                        "variables": variables,
                        "repeat_index": repeat_index,
                        "prompt": prompt,
                    }
                )
    return tasks


def _public_model(model_ref: Mapping[str, Any]) -> Dict[str, Any]:
    provider = model_ref["provider"]
    return {
        "name": model_ref["name"],
        "id": model_ref["id"],
        "provider": model_ref["provider_name"],
        "provider_type": provider["type"],
        "base_url": provider["base_url"],
    }


def _error(exc: Exception) -> Dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


async def _call_provider(
    model_ref: Mapping[str, Any],
    messages: List[Dict[str, str]],
    generation: Dict[str, Any],
    runtime: Mapping[str, Any],
    limiters: ProviderLimiters,
) -> Dict[str, Any]:
    provider = dict(model_ref["provider"])
    provider["timeout_seconds"] = runtime["timeout_seconds"]
    completion = registry.get_provider_completion(provider["type"])
    async with limiters.get(model_ref["provider_name"]):
        return await completion(provider, model_ref["id"], messages, generation)


async def _run_task(
    task: Mapping[str, Any],
    config: Mapping[str, Any],
    model_index: Mapping[str, Mapping[str, Any]],
    limiters: ProviderLimiters,
) -> Dict[str, Any]:
    started_at = utc_now()
    started = time.perf_counter()
    runtime = config["runtime"]
    generation_messages = [{"role": "user", "content": task["prompt"]}]
    generation_settings = dict(config["generation"])
    base_record: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": task["task_id"],
        "experiment": config["experiment"]["name"],
        "model": _public_model(task["model_ref"]),
        "repeat_index": task["repeat_index"],
        "variables": task["variables"],
        "prompt": task["prompt"],
        "started_at": started_at,
        "generation": {
            "request": {
                "messages": generation_messages,
                "parameters": generation_settings,
            }
        },
        "judge": None,
        "normalized_option": None,
    }

    async def generate() -> Dict[str, Any]:
        return await _call_provider(
            task["model_ref"],
            generation_messages,
            generation_settings,
            runtime,
            limiters,
        )

    try:
        generation_response, attempts = await with_retry(
            generate, int(runtime["retries"])
        )
    except RetryExhausted as exc:
        base_record["generation"]["attempts"] = exc.attempts
        base_record["generation"]["error"] = _error(exc.last_error)
        base_record["status"] = "generation_error"
        base_record["finished_at"] = utc_now()
        base_record["duration_seconds"] = round(time.perf_counter() - started, 6)
        return base_record

    base_record["generation"]["attempts"] = attempts
    base_record["generation"]["response"] = generation_response

    judge_ref = model_index[config["judge"]["model"]]
    judge_messages = build_judge_messages(
        task["prompt"],
        generation_response.get("content") or "",
        config["experiment"]["options"],
    )
    judge_settings = {
        key: value for key, value in config["judge"].items() if key != "model"
    }
    judge_record: Dict[str, Any] = {
        "model": _public_model(judge_ref),
        "request": {"messages": judge_messages, "parameters": judge_settings},
    }
    base_record["judge"] = judge_record

    async def judge_answer() -> Dict[str, Any]:
        provider_response = await _call_provider(
            judge_ref,
            judge_messages,
            judge_settings,
            runtime,
            limiters,
        )
        try:
            parsed = parse_judge_response(
                provider_response.get("content"), config["experiment"]["options"]
            )
        except JudgeParseError as exc:
            exc.response = provider_response
            raise
        return {"response": provider_response, "parsed": parsed}

    try:
        judged, judge_attempts = await with_retry(
            judge_answer, int(runtime["retries"])
        )
    except RetryExhausted as exc:
        judge_record["attempts"] = exc.attempts
        judge_record["error"] = _error(exc.last_error)
        base_record["status"] = "judge_error"
        base_record["finished_at"] = utc_now()
        base_record["duration_seconds"] = round(time.perf_counter() - started, 6)
        return base_record

    judge_record["attempts"] = judge_attempts
    judge_record["response"] = judged["response"]
    judge_record["parsed"] = judged["parsed"]
    base_record["normalized_option"] = judged["parsed"]["option"]
    base_record["status"] = "complete"
    base_record["finished_at"] = utc_now()
    base_record["duration_seconds"] = round(time.perf_counter() - started, 6)
    return base_record


def _choose_records(
    records: Iterable[Mapping[str, Any]], task_ids: Sequence[str]
) -> Dict[str, Mapping[str, Any]]:
    allowed = set(task_ids)
    selected: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        task_id = record.get("task_id")
        if task_id not in allowed:
            continue
        previous = selected.get(task_id)
        if record.get("status") == "complete":
            selected[task_id] = record
        elif previous is None or previous.get("status") != "complete":
            selected[task_id] = record
    return selected


def _group_stats(
    task_records: Iterable[Tuple[Mapping[str, Any], Optional[Mapping[str, Any]]]],
    option_ids: Sequence[str],
    positive_option: str,
    unknown_option: str,
) -> Dict[str, Any]:
    counts = {option: 0 for option in option_ids}
    statuses: Dict[str, int] = defaultdict(int)
    planned = 0
    for _, record in task_records:
        planned += 1
        if record is None:
            statuses["pending"] += 1
            continue
        status = str(record.get("status", "unknown_error"))
        statuses[status] += 1
        if status == "complete":
            option = record.get("normalized_option")
            if option in counts:
                counts[str(option)] += 1

    valid_count = sum(
        count for option, count in counts.items() if option != unknown_option
    )
    positive_count = counts.get(positive_option, 0)
    return {
        "planned_count": planned,
        "completed_count": statuses.get("complete", 0),
        "valid_count": valid_count,
        "option_counts": counts,
        "positive_probability": (
            positive_count / valid_count if valid_count else None
        ),
        "unknown_count": counts.get(unknown_option, 0),
        "generation_error_count": statuses.get("generation_error", 0),
        "judge_error_count": statuses.get("judge_error", 0),
        "pending_count": statuses.get("pending", 0),
    }


def _value_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_summary(
    config: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected = _choose_records(records, [str(task["task_id"]) for task in tasks])
    option_ids = [str(option["id"]) for option in config["experiment"]["options"]]
    positive = str(config["experiment"]["positive_option"])
    unknown = str(config["experiment"]["unknown_option"])

    def stats(group_tasks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        return _group_stats(
            ((task, selected.get(str(task["task_id"]))) for task in group_tasks),
            option_ids,
            positive,
            unknown,
        )

    by_model: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_cell: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[Mapping[str, Any]]] = (
        defaultdict(list)
    )
    marginals: Dict[
        str, Dict[Tuple[str, str], List[Mapping[str, Any]]]
    ] = {
        name: defaultdict(list) for name in config["experiment"]["variables"]
    }

    for task in tasks:
        model = str(task["model"])
        by_model[model].append(task)
        cell_values = tuple(
            (name, _value_key(item["value"]))
            for name, item in task["variables"].items()
        )
        by_cell[(model, cell_values)].append(task)
        for variable_name, item in task["variables"].items():
            marginals[variable_name][(model, _value_key(item["value"]))].append(task)

    models = [
        {"model": model, **stats(group)}
        for model, group in sorted(by_model.items())
    ]
    cells = []
    for (model, _), group in sorted(by_cell.items(), key=lambda item: item[0]):
        variables = group[0]["variables"]
        cells.append({"model": model, "variables": variables, **stats(group)})

    marginal_output: Dict[str, List[Dict[str, Any]]] = {}
    for variable_name, groups in marginals.items():
        entries = []
        for (model, _), group in sorted(groups.items(), key=lambda item: item[0]):
            entries.append(
                {
                    "model": model,
                    "variable": group[0]["variables"][variable_name],
                    **stats(group),
                }
            )
        marginal_output[variable_name] = entries

    return {
        "schema_version": 1,
        "experiment": config["experiment"]["name"],
        "generated_at": utc_now(),
        "positive_option": positive,
        "unknown_option": unknown,
        "overall": stats(tasks),
        "models": models,
        "cells": cells,
        "marginals": marginal_output,
    }


async def run(config_path: Path) -> Dict[str, Any]:
    config = load_config(config_path)
    tasks = build_tasks(config)
    jsonl_path = Path(config["output"]["jsonl"])
    summary_path = Path(config["output"]["summary"])
    existing = read_jsonl(jsonl_path)
    current_task_ids = {str(task["task_id"]) for task in tasks}
    completed_ids = {
        str(record["task_id"])
        for record in existing
        if record.get("status") == "complete"
        and record.get("task_id") in current_task_ids
    }
    pending = [task for task in tasks if task["task_id"] not in completed_ids]
    model_index = build_model_index(config)
    used_aliases = set(config["experiment"]["models"]) | {config["judge"]["model"]}
    active_providers = {
        model_index[alias]["provider_name"] for alias in used_aliases
    }
    variable_sizes = {
        name: len(values)
        for name, values in config["experiment"]["variables"].items()
    }
    scenario_count = math.prod(variable_sizes.values())
    model_condition_count = scenario_count * len(config["experiment"]["models"])
    repeats = int(config["experiment"]["repeats"])
    retries = int(config["runtime"]["retries"])
    expected_requests = len(tasks) * 2
    maximum_requests = expected_requests * retries
    variables_text = ",".join(
        f"{name}:{size}" for name, size in variable_sizes.items()
    )
    print(
        f"[start] experiment={config['experiment']['name']} "
        f"providers={len(active_providers)} models={len(config['experiment']['models'])} "
        f"variables={variables_text} scenarios={scenario_count} "
        f"model_conditions={model_condition_count} repeats={repeats} "
        f"tasks={len(tasks)} resumed={len(completed_ids)} pending={len(pending)} "
        f"api_expected={expected_requests} api_max={maximum_requests}",
        flush=True,
    )

    historical_records = [
        record for record in existing if record.get("task_id") in current_task_ids
    ]
    progress: Dict[str, int] = {
        "finished": 0,
        "in_flight": 0,
        "complete": 0,
        "unknown": 0,
        "generation_error": 0,
        "judge_error": 0,
        "generation_attempts": sum(
            _attempt_count(record, "generation") for record in historical_records
        ),
        "judge_attempts": sum(
            _attempt_count(record, "judge") for record in historical_records
        ),
    }
    run_started = time.perf_counter()

    def print_progress(final: bool = False) -> None:
        elapsed = time.perf_counter() - run_started
        run_finished = progress["finished"]
        total_processed = len(completed_ids) + run_finished
        percent = total_processed / len(tasks) * 100 if tasks else 100.0
        speed = run_finished / elapsed * 60 if elapsed > 0 else 0.0
        remaining = max(0, len(pending) - run_finished)
        eta = remaining / (run_finished / elapsed) if run_finished and elapsed > 0 else None
        eta_text = _format_duration(eta) if eta is not None else "--:--:--"
        api_total = progress["generation_attempts"] + progress["judge_attempts"]
        label = "done" if final else "progress"
        print(
            f"[{label}] providers={len(active_providers)} "
            f"models={len(config['experiment']['models'])} variables={variables_text} "
            f"tasks={total_processed}/{len(tasks)} ({percent:.1f}%) "
            f"run={run_finished}/{len(pending)} active={progress['in_flight']} "
            f"success={len(completed_ids) + progress['complete']} "
            f"unknown={progress['unknown']} gen_error={progress['generation_error']} "
            f"judge_error={progress['judge_error']} elapsed={_format_duration(elapsed)} "
            f"speed={speed:.2f}/min eta={eta_text} "
            f"api_gen={progress['generation_attempts']} "
            f"api_judge={progress['judge_attempts']} api_total={api_total}",
            flush=True,
        )

    writer = JsonlWriter(jsonl_path)
    limiters = ProviderLimiters(config["providers"])
    queue: asyncio.Queue = asyncio.Queue()
    for task in pending:
        queue.put_nowait(task)

    async def worker() -> None:
        while True:
            try:
                task = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            progress["in_flight"] += 1
            try:
                record = await _run_task(task, config, model_index, limiters)
                await writer.append(record)
            finally:
                progress["in_flight"] -= 1
                progress["finished"] += 1
                queue.task_done()
            status = str(record.get("status"))
            if status in progress:
                progress[status] += 1
            if status == "complete" and record.get("normalized_option") == config["experiment"]["unknown_option"]:
                progress["unknown"] += 1
            progress["generation_attempts"] += _attempt_count(record, "generation")
            progress["judge_attempts"] += _attempt_count(record, "judge")

    stop_reporting = asyncio.Event()

    async def reporter() -> None:
        interval = float(config["runtime"].get("progress_interval_seconds", 10))
        while True:
            try:
                await asyncio.wait_for(stop_reporting.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                print_progress()

    worker_count = min(int(config["runtime"]["workers"]), len(pending))
    if worker_count:
        reporter_task = asyncio.create_task(reporter())
        try:
            await asyncio.gather(*(worker() for _ in range(worker_count)))
        finally:
            stop_reporting.set()
            await reporter_task
    print_progress(final=True)

    records = read_jsonl(jsonl_path)
    summary = build_summary(config, tasks, records)
    write_json_atomic(summary_path, summary)

    print(f"[output] results={jsonl_path} summary={summary_path}", flush=True)
    for model in summary["models"]:
        probability = model["positive_probability"]
        rendered_probability = "n/a" if probability is None else f"{probability:.1%}"
        print(
            f"  {model['model']}: P({summary['positive_option']})="
            f"{rendered_probability}, valid={model['valid_count']}, "
            f"unknown={model['unknown_count']}"
        )
    return summary
