import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_response(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "json"):
        try:
            return value.json()
        except Exception:
            pass
    status_code = getattr(value, "status_code", None)
    text = getattr(value, "text", None)
    if status_code is not None or text is not None:
        return {"status_code": status_code, "body": text}
    return str(value)


def _error_record(exc: Exception) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    response = getattr(exc, "response", None)
    if response is not None:
        record["response"] = _safe_response(response)
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        record["status_code"] = status_code
    return record


class RetryExhausted(RuntimeError):
    def __init__(self, attempts: List[Dict[str, Any]], last_error: Exception):
        super().__init__(str(last_error))
        self.attempts = attempts
        self.last_error = last_error


async def with_retry(
    operation: Callable[[], Awaitable[Any]],
    retries: int,
    base_delay: float = 1.0,
) -> Tuple[Any, List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []
    last_error: Optional[Exception] = None

    for number in range(1, retries + 1):
        started_at = utc_now()
        started = time.perf_counter()
        try:
            result = await operation()
        except Exception as exc:  # Provider SDKs expose many exception subclasses.
            last_error = exc
            attempts.append(
                {
                    "attempt": number,
                    "started_at": started_at,
                    "duration_seconds": round(time.perf_counter() - started, 6),
                    "status": "error",
                    "error": _error_record(exc),
                }
            )
            if number < retries:
                delay = base_delay * (2 ** (number - 1))
                await asyncio.sleep(delay + random.uniform(0, delay * 0.1))
            continue

        attempts.append(
            {
                "attempt": number,
                "started_at": started_at,
                "duration_seconds": round(time.perf_counter() - started, 6),
                "status": "success",
            }
        )
        return result, attempts

    assert last_error is not None
    raise RetryExhausted(attempts, last_error)
