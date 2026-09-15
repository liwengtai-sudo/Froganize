"""Single-request stdin/stdout bridge used by the Froganize menu-bar agent."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any, BinaryIO

from dropnest.intelligence_contract import (
    MAX_REQUEST_BYTES,
    SCHEMA_VERSION,
    ContractError,
    parse_request_bytes,
)
from dropnest.intelligence_history import (
    IntelligencePaths,
    IntelligenceStorageError,
    default_paths,
)
from dropnest.screenshot_operations import ScreenshotOperationError, execute_request


def error_response(
    *,
    request_id: str | None,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build the only machine-readable error shape emitted by the helper."""
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": "error",
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


def handle_payload(
    payload: bytes,
    *,
    paths: IntelligencePaths | None = None,
) -> dict[str, Any]:
    """Validate and execute one payload; expected failures never escape."""
    request_id: str | None = None
    try:
        request = parse_request_bytes(payload)
        request_id = request.request_id
        return execute_request(request, paths or default_paths())
    except ContractError as exc:
        return error_response(
            request_id=exc.request_id,
            code=exc.code,
            message=str(exc),
        )
    except ScreenshotOperationError as exc:
        return error_response(
            request_id=request_id,
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
        )
    except IntelligenceStorageError as exc:
        return error_response(
            request_id=request_id,
            code=exc.code,
            message=str(exc),
        )
    except Exception:
        # stdout is a protocol channel: never expose paths, secrets, or a traceback.
        return error_response(
            request_id=request_id,
            code="internal_error",
            message="The Froganize file-operation helper failed safely.",
        )


def _write_response(stream: BinaryIO, response: dict[str, Any]) -> None:
    encoded = (
        json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    stream.write(encoded)
    stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """Read one bounded request from stdin and write exactly one JSON response."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        response = error_response(
            request_id=None,
            code="unexpected_argument",
            message="froganize-fileops accepts JSON on stdin and no arguments.",
        )
        _write_response(sys.stdout.buffer, response)
        return 2
    payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    response = handle_payload(payload)
    _write_response(sys.stdout.buffer, response)
    return 2 if response["status"] == "error" else 0


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    raise SystemExit(main(sys.argv[1:]))
