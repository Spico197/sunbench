import pytest

from sunbench.judge import JudgeParseError, build_judge_messages, parse_judge_response


OPTIONS = [
    {"id": "give", "description": "建议给"},
    {"id": "not_give", "description": "建议不给"},
    {"id": "unclear", "description": "不明确"},
]


def test_build_judge_prompt_contains_question_answer_and_options():
    messages = build_judge_messages("原问题", "给", OPTIONS)
    content = messages[0]["content"]
    assert "原问题" in content
    assert "给" in content
    assert "not_give" in content


@pytest.mark.parametrize(
    "content",
    [
        '{"option":"give","reason":"明确"}',
        '```json\n{"option":" GIVE ","reason":"明确"}\n```',
        '结果如下：{"option":"give","reason":"明确"}',
    ],
)
def test_parse_judge_response(content):
    parsed = parse_judge_response(content, OPTIONS)
    assert parsed == {"option": "give", "reason": "明确"}


def test_unknown_option_is_rejected():
    with pytest.raises(JudgeParseError, match="Unknown judge option"):
        parse_judge_response('{"option":"maybe"}', OPTIONS)

