"""Versioned JSON contract for the Froganize Screenshot Intelligence helper."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass
from typing import Any, TypeAlias

SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
MAX_SOURCE_NAME_BYTES = 255
MAX_SOURCE_ROOT_LENGTH = 4096
MAX_TITLE_LENGTH = 512
MAX_SUMMARY_LENGTH = 4000
MAX_CATEGORY_LENGTH = 128
MAX_PROVIDER_LENGTH = 128
MAX_MODEL_LENGTH = 256
ALLOWED_CATEGORIES = frozenset(
    {"聊天", "网页", "代码", "文档", "报错", "图片", "数据", "其他"}
)

ACTION_CONFIGURE = "configure_screenshot_root"
ACTION_RENAME = "rename_screenshot"
ACTION_UNDO = "undo_screenshot_rename"


class ContractError(ValueError):
    """A stable, user-safe validation failure for an untrusted request."""

    def __init__(self, code: str, message: str, *, request_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class ScreenshotSnapshot:
    """Filesystem identity captured before the AI request starts."""

    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class ScreenshotAnalysis:
    """Untrusted semantic output supplied by the configured AI provider."""

    title: str
    summary: str
    category: str
    confidence: float
    sensitive: bool


@dataclass(frozen=True, slots=True)
class ConfigureScreenshotRootRequest:
    schema_version: int
    request_id: str
    action: str
    source_root: str


@dataclass(frozen=True, slots=True)
class RenameScreenshotRequest:
    schema_version: int
    request_id: str
    action: str
    source_name: str
    snapshot: ScreenshotSnapshot
    analysis: ScreenshotAnalysis
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class UndoScreenshotRenameRequest:
    schema_version: int
    request_id: str
    action: str
    event_id: str | None


IntelligenceRequest: TypeAlias = (
    ConfigureScreenshotRootRequest
    | RenameScreenshotRequest
    | UndoScreenshotRenameRequest
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_json_key", f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _require_exact_fields(
    data: dict[str, Any],
    expected: set[str],
    *,
    request_id: str | None,
    label: str = "request",
) -> None:
    missing = expected.difference(data)
    if missing:
        raise ContractError(
            "missing_field",
            f"The {label} is missing fields: {', '.join(sorted(missing))}.",
            request_id=request_id,
        )
    unknown = set(data).difference(expected)
    if unknown:
        raise ContractError(
            "unknown_field",
            f"The {label} contains unknown fields: {', '.join(sorted(unknown))}.",
            request_id=request_id,
        )


def _text(
    value: object,
    field: str,
    *,
    maximum: int,
    request_id: str | None,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContractError(
            "invalid_field",
            f"Field {field} must be a string.",
            request_id=request_id,
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ContractError(
            "invalid_unicode",
            f"Field {field} contains invalid Unicode.",
            request_id=request_id,
        ) from exc
    if "\x00" in value:
        raise ContractError(
            "invalid_field",
            f"Field {field} contains a NUL character.",
            request_id=request_id,
        )
    if not allow_empty and not value.strip():
        raise ContractError(
            "invalid_field",
            f"Field {field} may not be empty.",
            request_id=request_id,
        )
    if len(value) > maximum:
        raise ContractError(
            "field_too_long",
            f"Field {field} exceeds its maximum length.",
            request_id=request_id,
        )
    return value


def _identifier(value: object, field: str, *, request_id: str | None) -> str:
    text = _text(value, field, maximum=64, request_id=request_id)
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError) as exc:
        raise ContractError(
            "invalid_id",
            f"Field {field} must be a UUID.",
            request_id=request_id,
        ) from exc


def _integer(value: object, field: str, *, request_id: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(
            "invalid_snapshot",
            f"Snapshot field {field} must be a non-negative integer.",
            request_id=request_id,
        )
    return value


def _snapshot(value: object, *, request_id: str) -> ScreenshotSnapshot:
    if not isinstance(value, dict):
        raise ContractError(
            "invalid_snapshot",
            "Field snapshot must be a JSON object.",
            request_id=request_id,
        )
    fields = {"device", "inode", "mode", "size", "mtime_ns"}
    _require_exact_fields(value, fields, request_id=request_id, label="snapshot")
    return ScreenshotSnapshot(
        device=_integer(value["device"], "device", request_id=request_id),
        inode=_integer(value["inode"], "inode", request_id=request_id),
        mode=_integer(value["mode"], "mode", request_id=request_id),
        size=_integer(value["size"], "size", request_id=request_id),
        mtime_ns=_integer(value["mtime_ns"], "mtime_ns", request_id=request_id),
    )


def _analysis(value: object, *, request_id: str) -> ScreenshotAnalysis:
    if not isinstance(value, dict):
        raise ContractError(
            "invalid_analysis",
            "Field analysis must be a JSON object.",
            request_id=request_id,
        )
    fields = {"title", "summary", "category", "confidence", "sensitive"}
    _require_exact_fields(value, fields, request_id=request_id, label="analysis")
    confidence = value["confidence"]
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        raise ContractError(
            "invalid_analysis",
            "Analysis confidence must be a finite number from 0 to 1.",
            request_id=request_id,
        )
    sensitive = value["sensitive"]
    if not isinstance(sensitive, bool):
        raise ContractError(
            "invalid_analysis",
            "Analysis sensitive must be a boolean.",
            request_id=request_id,
        )
    category = _text(
        value["category"],
        "analysis.category",
        maximum=MAX_CATEGORY_LENGTH,
        request_id=request_id,
    )
    if category not in ALLOWED_CATEGORIES:
        raise ContractError(
            "invalid_analysis",
            "Analysis category is not one of the supported categories.",
            request_id=request_id,
        )
    return ScreenshotAnalysis(
        title=_text(
            value["title"],
            "analysis.title",
            maximum=MAX_TITLE_LENGTH,
            request_id=request_id,
        ),
        summary=_text(
            value["summary"],
            "analysis.summary",
            maximum=MAX_SUMMARY_LENGTH,
            request_id=request_id,
            allow_empty=True,
        ),
        category=category,
        confidence=float(confidence),
        sensitive=sensitive,
    )


def parse_request_bytes(payload: bytes) -> IntelligenceRequest:
    """Decode and strictly validate one bounded UTF-8 JSON request."""
    if len(payload) > MAX_REQUEST_BYTES:
        raise ContractError("request_too_large", "Request exceeds 64 KiB.")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError("invalid_utf8", "Request is not valid UTF-8.") from exc
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ContractError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", "Request is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise ContractError("invalid_request", "Request must be a JSON object.")

    raw_request_id = raw.get("request_id")
    echoed_request_id = raw_request_id if isinstance(raw_request_id, str) else None
    if raw.get("schema_version") != SCHEMA_VERSION or isinstance(
        raw.get("schema_version"), bool
    ):
        raise ContractError(
            "unsupported_schema",
            f"Only schema_version {SCHEMA_VERSION} is supported.",
            request_id=echoed_request_id,
        )
    request_id = _identifier(raw_request_id, "request_id", request_id=echoed_request_id)
    action = _text(
        raw.get("action"),
        "action",
        maximum=64,
        request_id=request_id,
    )

    common = {"schema_version", "request_id", "action"}
    if action == ACTION_CONFIGURE:
        _require_exact_fields(
            raw,
            common | {"source_root"},
            request_id=request_id,
        )
        return ConfigureScreenshotRootRequest(
            SCHEMA_VERSION,
            request_id,
            action,
            _text(
                raw["source_root"],
                "source_root",
                maximum=MAX_SOURCE_ROOT_LENGTH,
                request_id=request_id,
            ),
        )
    if action == ACTION_RENAME:
        _require_exact_fields(
            raw,
            common | {"source_name", "snapshot", "analysis", "provider", "model"},
            request_id=request_id,
        )
        source_name = _text(
            raw["source_name"],
            "source_name",
            maximum=MAX_SOURCE_NAME_BYTES,
            request_id=request_id,
        )
        if len(source_name.encode("utf-8")) > MAX_SOURCE_NAME_BYTES:
            raise ContractError(
                "field_too_long",
                "Field source_name exceeds the filesystem name limit.",
                request_id=request_id,
            )
        return RenameScreenshotRequest(
            SCHEMA_VERSION,
            request_id,
            action,
            source_name,
            _snapshot(raw["snapshot"], request_id=request_id),
            _analysis(raw["analysis"], request_id=request_id),
            _text(
                raw["provider"],
                "provider",
                maximum=MAX_PROVIDER_LENGTH,
                request_id=request_id,
            ),
            _text(
                raw["model"],
                "model",
                maximum=MAX_MODEL_LENGTH,
                request_id=request_id,
            ),
        )
    if action == ACTION_UNDO:
        expected = common | ({"event_id"} if "event_id" in raw else set())
        _require_exact_fields(raw, expected, request_id=request_id)
        event_id = raw.get("event_id")
        return UndoScreenshotRenameRequest(
            SCHEMA_VERSION,
            request_id,
            action,
            None
            if event_id is None
            else _identifier(event_id, "event_id", request_id=request_id),
        )
    raise ContractError(
        "unknown_action",
        f"Unknown action: {action}.",
        request_id=request_id,
    )


def request_fingerprint(request: IntelligenceRequest) -> str:
    """Return a stable digest used to detect unsafe request-id reuse."""
    payload = asdict(request)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
