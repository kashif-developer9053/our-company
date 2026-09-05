"""The shared error-isolation utility.

CRITICAL ARCHITECTURE RULE: every module is isolated so one module's failure
(a bug, a down dependency, a bad input) never crashes another module or the app.
Route handlers wrap their work with `safe_route` / the `@safe_endpoint`
decorator; background/module code can use `safe_call`. Failures are caught,
logged per-module, and turned into a clean error result instead of a crash.
"""

from __future__ import annotations

import functools
import traceback
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .logger import get_logger


def _record_error(module: str) -> None:
    """Log an error event for the IT Technician's spike detection. Best-effort —
    wrapped so a logging failure (e.g. DB down) never causes recursion/crashes."""
    try:
        from datetime import datetime, timezone

        from .database import get_db

        get_db()["error_events"].insert_one({"module": module, "at": datetime.now(timezone.utc).isoformat()})
    except Exception:  # noqa: BLE001
        pass


def safe_call(module: str, fn: Callable, *args, default: Any = None, **kwargs) -> Any:
    """Run fn, catching everything. On failure, log to the module's logger and
    return `default`. Used by module/background code that must never raise."""
    log = get_logger(module)
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - intentional catch-all for isolation
        log.error("safe_call failed: %s\n%s", exc, traceback.format_exc())
        _record_error(module)
        return default


def safe_endpoint(module: str) -> Callable:
    """Decorator for FastAPI route handlers. Lets intentional HTTPExceptions
    (404/400/etc.) pass through, but catches any unexpected error, logs it under
    the module, and returns a clean 500 JSON response so the server process and
    all other routers keep running."""

    def decorator(handler: Callable) -> Callable:
        log = get_logger(module)

        @functools.wraps(handler)
        async def wrapper(*args, **kwargs):
            try:
                return await handler(*args, **kwargs)
            except HTTPException:
                raise  # deliberate client errors — let FastAPI handle them
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "Unhandled error in %s.%s: %s\n%s",
                    module,
                    handler.__name__,
                    exc,
                    traceback.format_exc(),
                )
                _record_error(module)
                return JSONResponse(
                    status_code=500,
                    content={
                        "ok": False,
                        "module": module,
                        "error": f"{module} module error (isolated, app still running): {exc}",
                    },
                )

        return wrapper

    return decorator
