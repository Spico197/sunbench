import json
import re
from typing import Any, Dict, List, Mapping


class JudgeParseError(ValueError):
    def __init__(self, message: str, response: Any = None):
        super().__init__(message)
        self.response = response


def build_judge_messages(
    original_prompt: str,
    answer: str,
    options: List[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    rendered_options = "\n".join(
        f'- {option["id"]}: {option["description"]}' for option in options
    )
    prompt = f"""你是一个答案分类器，只判断被测模型的回答属于哪个选项，不要评价问题本身。

原始问题：
{original_prompt}

被测模型回答：
{answer}

可选选项：
{rendered_options}

只返回一个 JSON 对象，不要使用 Markdown：
{{"option":"选项ID","reason":"简短原因"}}
"""
    return [{"role": "user", "content": prompt}]


def _extract_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise JudgeParseError("Judge did not return a JSON object")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise JudgeParseError("Judge returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise JudgeParseError("Judge result must be a JSON object")
    return value


def parse_judge_response(text: Any, options: List[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise JudgeParseError("Judge returned empty content")
    value = _extract_json(text)
    raw_option = value.get("option")
    if not isinstance(raw_option, str):
        raise JudgeParseError("Judge result is missing a string option")
    canonical = {str(option["id"]).strip().lower(): str(option["id"]) for option in options}
    normalized = canonical.get(raw_option.strip().lower())
    if normalized is None:
        raise JudgeParseError(f"Unknown judge option: {raw_option}")
    reason = value.get("reason", "")
    return {
        "option": normalized,
        "reason": reason if isinstance(reason, str) else str(reason),
    }
