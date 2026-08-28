import asyncio
import json

from sunbench import analyze


def _record(task_id, model, option, reasoning):
    return {
        "task_id": task_id,
        "experiment": "test",
        "status": "complete",
        "model": {"name": model},
        "repeat_index": 1,
        "variables": {"target": {"text": "他", "value": "male"}},
        "prompt": "给吗？",
        "normalized_option": option,
        "generation": {
            "response": {
                "content": "给",
                "reasoning_content": reasoning,
            }
        },
    }


def test_build_analysis_messages_marks_missing_and_truncated_reasoning(monkeypatch):
    monkeypatch.setattr(analyze, "REASONING_CHARS_PER_SAMPLE", 10)
    records = [
        _record("a", "model-a", "give", "123456789012345"),
        _record("b", "model-a", "not_give", None),
    ]

    messages, evidence = analyze.build_analysis_messages("model-a", records)

    assert evidence == {
        "sample_count": 2,
        "option_counts": {"give": 1, "not_give": 1},
        "visible_reasoning_count": 1,
        "truncated_reasoning_count": 1,
    }
    assert "中间省略" in messages[0]["content"]
    assert '"visible_reasoning": null' in messages[0]["content"]


def test_parse_analysis_response_accepts_fence_and_checks_sections():
    value = {key: {} for key in analyze.REQUIRED_ANALYSIS_SECTIONS}
    parsed = analyze.parse_analysis_response(
        "```json\n" + json.dumps(value) + "\n```"
    )
    assert parsed == value

    try:
        analyze.parse_analysis_response('{"style": {}}')
    except analyze.AnalysisParseError as exc:
        assert "missing object section" in str(exc)
    else:
        raise AssertionError("Expected AnalysisParseError")


def test_analyze_records_writes_json_and_resumes(tmp_path, monkeypatch, copy_config):
    records = [
        _record("a", "model-a", "give", "考虑比例后建议给"),
        _record("b", "model-a", "give", None),
    ]
    calls = []
    response_value = {
        "style": {"summary": "直接"},
        "content": {"decision_tendency": "倾向给"},
        "reasoning": {"availability": "部分可见"},
        "overall": {"portrait": "简洁"},
    }

    async def fake_completion(provider, model_id, messages, generation):
        calls.append((model_id, messages, generation))
        return {
            "content": json.dumps(response_value, ensure_ascii=False),
            "reasoning_content": "分析过程",
            "usage": {"total_tokens": 10},
            "model": model_id,
        }

    monkeypatch.setattr(
        analyze.registry, "get_provider_completion", lambda _: fake_completion
    )
    output = tmp_path / "analysis.json"

    first = asyncio.run(
        analyze.analyze_records(
            copy_config,
            records,
            output,
            analyzer_model="judge-model",
        )
    )
    second = asyncio.run(
        analyze.analyze_records(
            copy_config,
            records,
            output,
            analyzer_model="judge-model",
        )
    )

    assert len(calls) == 1
    assert first["completed_count"] == 1
    assert second["completed_count"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["models"][0]["analysis"] == response_value
    assert saved["models"][0]["visible_reasoning_count"] == 1
    assert saved["models"][0]["analyzer_response"]["reasoning_content"] == "分析过程"
