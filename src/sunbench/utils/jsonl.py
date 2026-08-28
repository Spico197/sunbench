import asyncio
import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    last_nonempty = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    records: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == last_nonempty:
                warnings.warn(
                    f"Ignoring malformed final JSONL line in {path}", RuntimeWarning
                )
                continue
            raise ValueError(f"Malformed JSONL at {path}:{index + 1}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record at {path}:{index + 1} is not an object")
        records.append(value)
    return records


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock: Optional[asyncio.Lock] = None

    async def append(self, record: Dict[str, Any]) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()


def write_json_atomic(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
