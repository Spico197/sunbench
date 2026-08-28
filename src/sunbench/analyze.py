import asyncio
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sunbench.config import build_model_index, load_config
from sunbench.utils import registry
from sunbench.utils.concurrency import ProviderLimiters
from sunbench.utils.jsonl import read_jsonl, write_json_atomic
from sunbench.utils.retry import RetryExhausted, utc_now, with_retry


DEFAULT_ANALYZER_MODEL = "deepseek-v4-flash"
DEFAULT_OUTPUT_NAME = "analysis.json"
REASONING_CHARS_PER_SAMPLE = 8000
REQUIRED_ANALYSIS_SECTIONS = ("style", "content", "reasoning", "overall")


class AnalysisParseError(ValueError):
    """Raised when the analyzer does not return the requested JSON object."""


def _model_name(record: Mapping[str, Any]) -> str:
    model = record.get("model")
    if isinstance(model, dict):
        return str(model.get("name", "unknown"))
    return str(model or "unknown")


def _latest_complete_records(
    records: Iterable[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    selected: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        task_id = str(record.get("task_id", ""))
        if not task_id or record.get("status") != "complete":
            continue
        selected[task_id] = record
    return list(selected.values())


def _truncate_middle(text: str, limit: int) -> Tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    marker = f"\n……[中间省略 {omitted} 个字符]……\n"
    return text[:head] + marker + text[-tail:], True


def _source_fingerprint(model: str, records: Sequence[Mapping[str, Any]]) -> str:
    source = []
    for record in sorted(records, key=lambda item: str(item.get("task_id", ""))):
        response = record.get("generation", {}).get("response", {})
        source.append(
            {
                "task_id": record.get("task_id"),
                "prompt": record.get("prompt"),
                "variables": record.get("variables"),
                "repeat_index": record.get("repeat_index"),
                "normalized_option": record.get("normalized_option"),
                "content": response.get("content"),
                "reasoning_content": response.get("reasoning_content"),
            }
        )
    encoded = json.dumps(
        {"model": model, "records": source},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _samples_for_prompt(
    records: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int]:
    samples: List[Dict[str, Any]] = []
    reasoning_count = 0
    truncated_count = 0
    ordered = sorted(
        records,
        key=lambda item: (
            json.dumps(item.get("variables", {}), ensure_ascii=False, sort_keys=True),
            int(item.get("repeat_index", 0)),
        ),
    )
    for record in ordered:
        response = record.get("generation", {}).get("response", {})
        reasoning = response.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            reasoning_count += 1
            visible_reasoning, truncated = _truncate_middle(
                reasoning, REASONING_CHARS_PER_SAMPLE
            )
            truncated_count += int(truncated)
        else:
            visible_reasoning = None
        samples.append(
            {
                "task_id": record.get("task_id"),
                "repeat_index": record.get("repeat_index"),
                "variables": record.get("variables"),
                "prompt": record.get("prompt"),
                "answer": response.get("content"),
                "normalized_option": record.get("normalized_option"),
                "visible_reasoning": visible_reasoning,
            }
        )
    return samples, reasoning_count, truncated_count


def build_analysis_messages(
    model: str, records: Sequence[Mapping[str, Any]]
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    samples, reasoning_count, truncated_count = _samples_for_prompt(records)
    option_counts = Counter(
        str(record.get("normalized_option", "unknown")) for record in records
    )
    evidence = {
        "sample_count": len(records),
        "option_counts": dict(sorted(option_counts.items())),
        "visible_reasoning_count": reasoning_count,
        "truncated_reasoning_count": truncated_count,
    }
    prompt = f"""你是一名严谨的大模型行为分析员。请基于下面同一个模型的全部实验样本，分析其回复风格、回复内容，以及 JSONL 中实际保存的可见思考过程。

模型：{model}
样本统计：{json.dumps(evidence, ensure_ascii=False)}

重要规则：
1. 只依据给出的 answer、normalized_option 和 visible_reasoning，不得补写、还原或猜测模型未提供的隐藏思考过程。
2. visible_reasoning 为 null 时，只能说明该样本未保存可见思考，不能断言模型没有推理。
3. 某些超长 visible_reasoning 已保留首尾并标记中间截断；分析时必须说明这一证据限制。
4. 区分“最终回答的表达风格”和“可见思考过程的风格”。关注是否遵守三字限制、直接程度、稳定性、对象差异、决策倾向、常见论据、风险观和回答与思考是否一致。
5. 总结跨样本模式，也指出反例与不确定性。不要评价模型厂商，不要引用外部知识。
6. 使用中文。只返回一个 JSON 对象，不要 Markdown，不要附加文字。

返回结构必须为：
{{
  "style": {{
    "summary": "总体回复风格",
    "directness": "直接程度",
    "instruction_following": "对不超过三个字等要求的遵守情况",
    "tone": "语气",
    "consistency": "跨样本一致性",
    "patterns": ["可核验的风格模式"]
  }},
  "content": {{
    "decision_tendency": "决策倾向",
    "target_differences": "他/她/它之间的差异；无证据则明确说无",
    "rationale_patterns": ["内容或论据模式"],
    "risk_attitude": "风险与金钱观",
    "answer_quality": "回答内容的有效性与局限"
  }},
  "reasoning": {{
    "availability": "可见思考覆盖情况",
    "summary": "只对可见思考的概括",
    "depth_and_structure": "深度与结构",
    "recurring_factors": ["反复考虑的因素"],
    "strengths": ["可见思考的优点"],
    "limitations": ["证据或思考的局限"],
    "answer_alignment": "可见思考与最终回答的一致性"
  }},
  "overall": {{
    "portrait": "简洁的模型画像",
    "distinguishing_traits": ["最有区分度的特点"],
    "caveats": ["解读时的注意事项"]
  }}
}}

实验样本：
{json.dumps(samples, ensure_ascii=False, indent=2)}
"""
    return [{"role": "user", "content": prompt}], evidence


def parse_analysis_response(text: Any) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise AnalysisParseError("Analyzer returned empty content")
    cleaned = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise AnalysisParseError("Analyzer did not return a JSON object")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise AnalysisParseError("Analyzer returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AnalysisParseError("Analyzer result must be a JSON object")
    missing = [key for key in REQUIRED_ANALYSIS_SECTIONS if not isinstance(value.get(key), dict)]
    if missing:
        raise AnalysisParseError(
            "Analyzer result is missing object section(s): " + ", ".join(missing)
        )
    return value


def _public_model(model_ref: Mapping[str, Any]) -> Dict[str, Any]:
    provider = model_ref["provider"]
    return {
        "name": model_ref["name"],
        "id": model_ref["id"],
        "provider": model_ref["provider_name"],
        "provider_type": provider["type"],
        "base_url": provider["base_url"],
    }


def _load_existing(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(value, dict) or not isinstance(value.get("models"), list):
        return {}
    return {
        str(item.get("model")): item
        for item in value["models"]
        if isinstance(item, dict) and item.get("model")
    }


async def analyze_records(
    config: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    output_path: Path,
    source_path: Optional[Path] = None,
    analyzer_model: str = DEFAULT_ANALYZER_MODEL,
) -> Dict[str, Any]:
    complete_records = _latest_complete_records(records)
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in complete_records:
        groups[_model_name(record)].append(record)
    if not groups:
        raise ValueError("No complete records found to analyze")

    model_index = build_model_index(config)
    if analyzer_model not in model_index:
        raise ValueError(f"Analyzer model alias not found in config: {analyzer_model}")
    analyzer_ref = model_index[analyzer_model]
    provider = dict(analyzer_ref["provider"])
    provider["timeout_seconds"] = max(
        180, int(config["runtime"].get("timeout_seconds", 180))
    )
    completion = registry.get_provider_completion(provider["type"])
    settings = {
        key: value for key, value in config["judge"].items() if key != "model"
    }
    retries = int(config["runtime"].get("retries", 3))
    limiters = ProviderLimiters(config["providers"])
    existing = _load_existing(output_path)
    results: Dict[str, Dict[str, Any]] = dict(existing)
    fingerprints = {
        model: _source_fingerprint(model, model_records)
        for model, model_records in groups.items()
    }
    pending = [
        model
        for model in sorted(groups)
        if not (
            results.get(model, {}).get("status") == "complete"
            and results[model].get("source_fingerprint") == fingerprints[model]
            and results[model].get("analyzer", {}).get("id") == analyzer_ref["id"]
        )
    ]

    def document() -> Dict[str, Any]:
        current = [results[model] for model in sorted(groups) if model in results]
        return {
            "schema_version": 1,
            "experiment": (
                complete_records[0].get("experiment") if complete_records else None
            ),
            "generated_at": utc_now(),
            "source_results": str(source_path.resolve()) if source_path else None,
            "analyzer": _public_model(analyzer_ref),
            "analysis_parameters": settings,
            "model_count": len(groups),
            "completed_count": sum(item.get("status") == "complete" for item in current),
            "error_count": sum(item.get("status") == "error" for item in current),
            "models": current,
        }

    print(
        f"[analysis-start] analyzer={analyzer_model} models={len(groups)} "
        f"resumed={len(groups) - len(pending)} pending={len(pending)} output={output_path}",
        flush=True,
    )
    write_lock = asyncio.Lock()
    completed_this_run = 0
    started = time.perf_counter()

    async def analyze_model(model: str) -> None:
        nonlocal completed_this_run
        messages, evidence = build_analysis_messages(model, groups[model])

        async def operation() -> Dict[str, Any]:
            async with limiters.get(analyzer_ref["provider_name"]):
                response = await completion(
                    provider, analyzer_ref["id"], messages, settings
                )
            parsed = parse_analysis_response(response.get("content"))
            return {"response": response, "parsed": parsed}

        entry: Dict[str, Any] = {
            "model": model,
            "source_fingerprint": fingerprints[model],
            "sample_count": evidence["sample_count"],
            "option_counts": evidence["option_counts"],
            "visible_reasoning_count": evidence["visible_reasoning_count"],
            "truncated_reasoning_count": evidence["truncated_reasoning_count"],
            "analyzer": _public_model(analyzer_ref),
        }
        try:
            analyzed, attempts = await with_retry(operation, retries)
        except RetryExhausted as exc:
            entry.update(
                {
                    "status": "error",
                    "attempts": exc.attempts,
                    "error": {
                        "type": type(exc.last_error).__name__,
                        "message": str(exc.last_error),
                    },
                    "finished_at": utc_now(),
                }
            )
        else:
            response = analyzed["response"]
            entry.update(
                {
                    "status": "complete",
                    "attempts": attempts,
                    "analysis": analyzed["parsed"],
                    "analyzer_response": {
                        "content": response.get("content"),
                        "reasoning_content": response.get("reasoning_content"),
                        "usage": response.get("usage"),
                        "model": response.get("model"),
                    },
                    "finished_at": utc_now(),
                }
            )

        async with write_lock:
            results[model] = entry
            completed_this_run += 1
            write_json_atomic(output_path, document())
            elapsed = time.perf_counter() - started
            speed = completed_this_run / elapsed * 60 if elapsed else 0.0
            remaining = len(pending) - completed_this_run
            eta = remaining / (completed_this_run / elapsed) if completed_this_run else 0
            print(
                f"[analysis-progress] models={completed_this_run}/{len(pending)} "
                f"model={model} status={entry['status']} elapsed={elapsed:.1f}s "
                f"speed={speed:.2f}/min eta={eta:.1f}s",
                flush=True,
            )

    worker_count = min(4, int(config["runtime"].get("workers", 1)), len(pending))
    if worker_count:
        queue: asyncio.Queue = asyncio.Queue()
        for model in pending:
            queue.put_nowait(model)

        async def worker() -> None:
            while True:
                try:
                    model = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await analyze_model(model)
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(worker_count)))
    final = document()
    write_json_atomic(output_path, final)
    print(
        f"[analysis-done] models={final['completed_count']}/{len(groups)} "
        f"errors={final['error_count']} output={output_path}",
        flush=True,
    )
    return final


async def analyze_run(
    config_path: Path,
    run_directory: Path,
    analyzer_model: str = DEFAULT_ANALYZER_MODEL,
) -> Dict[str, Any]:
    config = load_config(config_path)
    run_directory = run_directory.expanduser().resolve()
    source_path = run_directory / "results.jsonl"
    if not source_path.is_file():
        raise FileNotFoundError(f"Results file not found: {source_path}")
    return await analyze_records(
        config,
        read_jsonl(source_path),
        run_directory / DEFAULT_OUTPUT_NAME,
        source_path=source_path,
        analyzer_model=analyzer_model,
    )
