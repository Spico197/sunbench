import asyncio
import json

import pytest

from sunbench.utils.jsonl import JsonlWriter, read_jsonl


def test_jsonl_writer_and_reader(tmp_path):
    path = tmp_path / "nested" / "results.jsonl"
    writer = JsonlWriter(path)

    async def write():
        await asyncio.gather(*(writer.append({"value": i}) for i in range(20)))

    asyncio.run(write())
    records = read_jsonl(path)
    assert sorted(record["value"] for record in records) == list(range(20))


def test_malformed_final_line_is_ignored(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text('{"ok":1}\n{"broken":', encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="malformed final"):
        assert read_jsonl(path) == [{"ok": 1}]


def test_malformed_middle_line_is_rejected(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text('{"ok":1}\nnope\n{"ok":2}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=":2"):
        read_jsonl(path)

