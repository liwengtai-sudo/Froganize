"""Private, append-only persistence for Screenshot Intelligence activity."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dropnest.exceptions import DropNestError
from dropnest.intelligence_contract import ScreenshotAnalysis, ScreenshotSnapshot

CONFIG_SCHEMA_VERSION = 1
ACTIVITY_SCHEMA_VERSION = 1
EVENT_RENAME = "screenshot_rename"
EVENT_UNDO = "screenshot_rename_undo"
RESULT_SUCCESS = "success"


class IntelligenceStorageError(DropNestError):
    """Intelligence state is missing, unsafe, damaged, or not writable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IntelligencePaths:
    """All non-secret local paths used by the helper."""

    root: Path
    intelligence: Path
    config: Path
    activity: Path
    operations: Path
    pending: Path
    lock: Path

    @classmethod
    def from_root(cls, root: Path) -> IntelligencePaths:
        absolute = Path(os.path.abspath(os.fspath(root.expanduser())))
        intelligence = absolute / "intelligence"
        operations = absolute / "operations"
        return cls(
            root=absolute,
            intelligence=intelligence,
            config=intelligence / "config.json",
            activity=intelligence / "activity.jsonl",
            operations=operations,
            pending=operations / "pending",
            lock=operations / "mutation.lock",
        )


@dataclass(frozen=True, slots=True)
class IntelligenceConfig:
    schema_version: int
    screenshot_root: str
    configured_at: str
    last_request_id: str
    last_request_fingerprint: str


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    """One committed rename or undo event; never contains screenshot bytes."""

    schema_version: int
    event_id: str
    request_id: str
    request_fingerprint: str
    event_type: str
    timestamp: str
    source_root: str
    original_name: str
    renamed_name: str
    result: str
    title: str
    summary: str
    category: str
    confidence: float
    sensitive: bool
    provider: str
    model: str
    undo_of_event_id: str | None
    snapshot: dict[str, int]


def default_paths() -> IntelligencePaths:
    """Return the application-support location, with a test/dev override."""
    override = os.environ.get("FROGANIZE_STATE_DIR") or os.environ.get(
        "FROGANIZE_APP_SUPPORT_ROOT"
    )
    root = (
        Path(override)
        if override
        else Path.home() / "Library" / "Application Support" / "Froganize"
    )
    return IntelligencePaths.from_root(root)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise IntelligenceStorageError(
            "unsafe_state_path", f"Intelligence directory cannot be a symlink: {path}"
        )
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise IntelligenceStorageError(
            "state_unavailable", f"Cannot prepare Intelligence directory: {path}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise IntelligenceStorageError(
            "unsafe_state_path", f"Intelligence path is not a safe directory: {path}"
        )


def ensure_state_layout(paths: IntelligencePaths) -> None:
    """Create only private app-support directories, never user content folders."""
    for directory in (
        paths.root,
        paths.intelligence,
        paths.operations,
        paths.pending,
    ):
        _require_private_directory(directory)
    for file_path in (paths.config, paths.activity, paths.lock):
        if file_path.is_symlink():
            raise IntelligenceStorageError(
                "unsafe_state_path", f"Intelligence file cannot be a symlink: {file_path}"
            )


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    ensure_state_layout(IntelligencePaths.from_root(path.parent.parent))
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            os.chmod(temporary_name, 0o600)
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        _sync_directory(path.parent)
    except OSError as exc:
        raise IntelligenceStorageError(
            "state_write_failed", f"Could not write Intelligence state: {path}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise IntelligenceStorageError("damaged_activity", f"{field} is not a UUID.")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise IntelligenceStorageError("damaged_activity", f"{field} is not a UUID.") from exc


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise IntelligenceStorageError(
            "damaged_activity", f"{field} is not a timestamp."
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise IntelligenceStorageError(
            "damaged_activity", f"{field} is not a timestamp."
        ) from exc
    return value


def write_config(
    paths: IntelligencePaths,
    *,
    screenshot_root: Path,
    request_id: str,
    request_fingerprint: str,
) -> IntelligenceConfig:
    config = IntelligenceConfig(
        CONFIG_SCHEMA_VERSION,
        str(screenshot_root),
        utc_now_text(),
        request_id,
        request_fingerprint,
    )
    _write_json_atomic(paths.config, asdict(config))
    return config


def load_config(
    paths: IntelligencePaths,
    *,
    create_state: bool = True,
) -> IntelligenceConfig:
    """Read the authorized screenshot root from strict, non-secret config."""
    if create_state:
        ensure_state_layout(paths)
    if not paths.config.exists():
        raise IntelligenceStorageError(
            "configuration_missing",
            "Screenshot Intelligence has no authorized screenshot folder.",
        )
    if paths.config.is_symlink():
        raise IntelligenceStorageError(
            "unsafe_state_path", "Screenshot Intelligence config cannot be a symlink."
        )
    try:
        raw = json.loads(paths.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntelligenceStorageError(
            "configuration_damaged", "Screenshot Intelligence config is damaged."
        ) from exc
    expected = set(IntelligenceConfig.__dataclass_fields__)
    if not isinstance(raw, dict) or set(raw) != expected:
        raise IntelligenceStorageError(
            "configuration_damaged", "Screenshot Intelligence config has invalid fields."
        )
    if raw["schema_version"] != CONFIG_SCHEMA_VERSION or isinstance(
        raw["schema_version"], bool
    ):
        raise IntelligenceStorageError(
            "configuration_damaged", "Screenshot Intelligence config version is unsupported."
        )
    if not isinstance(raw["screenshot_root"], str) or not Path(
        raw["screenshot_root"]
    ).is_absolute():
        raise IntelligenceStorageError(
            "configuration_damaged", "Configured screenshot folder is invalid."
        )
    _timestamp(raw["configured_at"], "configured_at")
    raw["last_request_id"] = _uuid(raw["last_request_id"], "last_request_id")
    if (
        not isinstance(raw["last_request_fingerprint"], str)
        or len(raw["last_request_fingerprint"]) != 64
    ):
        raise IntelligenceStorageError(
            "configuration_damaged", "Configuration request fingerprint is invalid."
        )
    return IntelligenceConfig(**raw)


def _validate_basename(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise IntelligenceStorageError(
            "damaged_activity", f"Activity field {field} is not a safe basename."
        )
    return value


def validate_activity_record(raw: object) -> ActivityRecord:
    if not isinstance(raw, dict) or set(raw) != set(ActivityRecord.__dataclass_fields__):
        raise IntelligenceStorageError(
            "damaged_activity", "Activity record has invalid fields."
        )
    if raw["schema_version"] != ACTIVITY_SCHEMA_VERSION or isinstance(
        raw["schema_version"], bool
    ):
        raise IntelligenceStorageError(
            "damaged_activity", "Activity record version is unsupported."
        )
    raw["event_id"] = _uuid(raw["event_id"], "event_id")
    raw["request_id"] = _uuid(raw["request_id"], "request_id")
    if raw["event_type"] not in {EVENT_RENAME, EVENT_UNDO}:
        raise IntelligenceStorageError(
            "damaged_activity", "Activity event type is unknown."
        )
    if raw["result"] != RESULT_SUCCESS:
        raise IntelligenceStorageError(
            "damaged_activity", "Activity result is invalid."
        )
    _timestamp(raw["timestamp"], "timestamp")
    if not isinstance(raw["source_root"], str) or not Path(raw["source_root"]).is_absolute():
        raise IntelligenceStorageError(
            "damaged_activity", "Activity source root is invalid."
        )
    raw["original_name"] = _validate_basename(raw["original_name"], "original_name")
    raw["renamed_name"] = _validate_basename(raw["renamed_name"], "renamed_name")
    for field in (
        "request_fingerprint",
        "title",
        "summary",
        "category",
        "provider",
        "model",
    ):
        if not isinstance(raw[field], str):
            raise IntelligenceStorageError(
                "damaged_activity", f"Activity field {field} is invalid."
            )
    confidence = raw["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise IntelligenceStorageError(
            "damaged_activity", "Activity confidence is invalid."
        )
    raw["confidence"] = float(confidence)
    if not isinstance(raw["sensitive"], bool):
        raise IntelligenceStorageError(
            "damaged_activity", "Activity sensitive flag is invalid."
        )
    undo_of = raw["undo_of_event_id"]
    if raw["event_type"] == EVENT_UNDO:
        raw["undo_of_event_id"] = _uuid(undo_of, "undo_of_event_id")
    elif undo_of is not None:
        raise IntelligenceStorageError(
            "damaged_activity", "Rename activity cannot reference an undo event."
        )
    snapshot = raw["snapshot"]
    expected_snapshot = {"device", "inode", "mode", "size", "mtime_ns"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected_snapshot:
        raise IntelligenceStorageError(
            "damaged_activity", "Activity snapshot is invalid."
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in snapshot.values()
    ):
        raise IntelligenceStorageError(
            "damaged_activity", "Activity snapshot values are invalid."
        )
    return ActivityRecord(**raw)


def read_activity(
    paths: IntelligencePaths,
    *,
    create_state: bool = True,
) -> tuple[ActivityRecord, ...]:
    """Read activity strictly; corruption blocks further file mutations."""
    if create_state:
        ensure_state_layout(paths)
    if not paths.activity.exists():
        return ()
    if paths.activity.is_symlink():
        raise IntelligenceStorageError(
            "unsafe_state_path", "Intelligence activity cannot be a symlink."
        )
    records: list[ActivityRecord] = []
    try:
        with paths.activity.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise IntelligenceStorageError(
                        "damaged_activity", f"Activity line {line_number} is blank."
                    )
                try:
                    raw = json.loads(line)
                    records.append(validate_activity_record(raw))
                except json.JSONDecodeError as exc:
                    raise IntelligenceStorageError(
                        "damaged_activity", f"Activity line {line_number} is damaged."
                    ) from exc
    except IntelligenceStorageError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise IntelligenceStorageError(
            "activity_read_failed", "Could not read Screenshot Intelligence activity."
        ) from exc
    return tuple(records)


def append_activity(paths: IntelligencePaths, record: ActivityRecord) -> None:
    """Append and fsync exactly one validated activity record."""
    validated = validate_activity_record(asdict(record))
    ensure_state_layout(paths)
    if paths.activity.is_symlink():
        raise IntelligenceStorageError(
            "unsafe_state_path", "Intelligence activity cannot be a symlink."
        )
    encoded = (
        json.dumps(
            asdict(validated),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(paths.activity, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("activity path is not a regular file")
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise IntelligenceStorageError(
            "activity_write_failed", "Could not append Screenshot Intelligence activity."
        ) from exc


def new_rename_record(
    *,
    request_id: str,
    request_fingerprint: str,
    source_root: Path,
    original_name: str,
    renamed_name: str,
    snapshot: ScreenshotSnapshot,
    analysis: ScreenshotAnalysis,
    provider: str,
    model: str,
) -> ActivityRecord:
    return ActivityRecord(
        ACTIVITY_SCHEMA_VERSION,
        str(uuid.uuid4()),
        request_id,
        request_fingerprint,
        EVENT_RENAME,
        utc_now_text(),
        str(source_root),
        original_name,
        renamed_name,
        RESULT_SUCCESS,
        analysis.title,
        analysis.summary,
        analysis.category,
        analysis.confidence,
        analysis.sensitive,
        provider,
        model,
        None,
        asdict(snapshot),
    )


def new_undo_record(
    *,
    request_id: str,
    request_fingerprint: str,
    original: ActivityRecord,
) -> ActivityRecord:
    return ActivityRecord(
        ACTIVITY_SCHEMA_VERSION,
        str(uuid.uuid4()),
        request_id,
        request_fingerprint,
        EVENT_UNDO,
        utc_now_text(),
        original.source_root,
        original.original_name,
        original.renamed_name,
        RESULT_SUCCESS,
        original.title,
        original.summary,
        original.category,
        original.confidence,
        original.sensitive,
        original.provider,
        original.model,
        original.event_id,
        dict(original.snapshot),
    )


def activity_for_request(
    records: tuple[ActivityRecord, ...], request_id: str
) -> ActivityRecord | None:
    matches = [record for record in records if record.request_id == request_id]
    if len(matches) > 1:
        raise IntelligenceStorageError(
            "damaged_activity", "Activity contains a duplicate request ID."
        )
    return matches[0] if matches else None


def outstanding_rename(
    records: tuple[ActivityRecord, ...], event_id: str | None = None
) -> ActivityRecord | None:
    undone = {
        record.undo_of_event_id
        for record in records
        if record.event_type == EVENT_UNDO and record.result == RESULT_SUCCESS
    }
    candidates = [
        record
        for record in records
        if record.event_type == EVENT_RENAME and record.event_id not in undone
    ]
    if event_id is None:
        return candidates[-1] if candidates else None
    return next((record for record in candidates if record.event_id == event_id), None)


def rename_by_event_id(
    records: tuple[ActivityRecord, ...], event_id: str
) -> ActivityRecord | None:
    return next(
        (
            record
            for record in records
            if record.event_type == EVENT_RENAME and record.event_id == event_id
        ),
        None,
    )
