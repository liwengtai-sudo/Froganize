"""Deterministic, local-only Screenshot Intelligence file operations."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import stat
import tempfile
import unicodedata
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from dropnest.intelligence_contract import (
    SCHEMA_VERSION,
    ConfigureScreenshotRootRequest,
    IntelligenceRequest,
    RenameScreenshotRequest,
    ScreenshotSnapshot,
    UndoScreenshotRenameRequest,
    request_fingerprint,
)
from dropnest.intelligence_history import (
    EVENT_RENAME,
    EVENT_UNDO,
    ActivityRecord,
    IntelligencePaths,
    IntelligenceStorageError,
    activity_for_request,
    append_activity,
    ensure_state_layout,
    load_config,
    new_rename_record,
    new_undo_record,
    outstanding_rename,
    read_activity,
    rename_by_event_id,
    validate_activity_record,
    write_config,
)
from dropnest.sorter import _casefold_name_is_occupied, _rename_no_replace

MINIMUM_CONFIDENCE = 0.35
MAX_SAFE_FILENAME_BYTES = 240
MAX_TITLE_CHARACTERS = 36
SUPPORTED_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "heic", "webp"})
SCREENSHOT_PATTERNS = (
    re.compile(r"^(截图|截屏)\s*\d{4}", re.IGNORECASE),
    re.compile(r"^Screenshot\s+\d{4}", re.IGNORECASE),
    re.compile(r"^Screen Shot\s+\d{4}", re.IGNORECASE),
)
FORBIDDEN_FILENAME_CHARACTERS = frozenset(
    "/:\\?!%*|\"<>：？！“”‘’《》【】（）()，,；;。"
)
JOURNAL_SCHEMA_VERSION = 1


class ScreenshotOperationError(Exception):
    """A stable, sanitized screenshot file-operation failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class MutationLock(AbstractContextManager["MutationLock"]):
    """Cross-process advisory gate for app-owned file mutations."""

    def __init__(self, paths: IntelligencePaths) -> None:
        self.paths = paths
        self._descriptor: int | None = None

    def __enter__(self) -> MutationLock:
        ensure_state_layout(self.paths)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.paths.lock, flags, 0o600)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("mutation lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            try:
                os.close(descriptor)
            except (OSError, UnboundLocalError):
                pass
            raise ScreenshotOperationError(
                "mutation_lock_failed", "Could not acquire the Froganize mutation lock."
            ) from exc
        self._descriptor = descriptor
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _safe_basename(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or len(name.encode("utf-8")) > 255
    ):
        raise ScreenshotOperationError(
            "invalid_source_name", "Screenshot source_name must be one safe basename."
        )
    return name


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _managed_roots(paths: IntelligencePaths) -> tuple[Path, ...]:
    home = Path.home().resolve(strict=False)
    candidates = [
        paths.root.resolve(strict=False),
        home / "Documents" / "FroganizeWorkspace",
        home / "Documents" / "DropNestWorkspace",
    ]
    configured = os.environ.get("FROGANIZE_WORKSPACE")
    if configured:
        candidates.append(Path(configured).expanduser().resolve(strict=False))
    return tuple(candidates)


def validate_screenshot_root(
    raw_path: str | Path,
    *,
    forbidden_roots: tuple[Path, ...] = (),
) -> Path:
    """Validate an explicitly selected source directory without following a root symlink."""
    raw = Path(raw_path).expanduser()
    if not raw.is_absolute() or ".." in raw.parts:
        raise ScreenshotOperationError(
            "invalid_source_root", "Screenshot folder must be an absolute path without '..'."
        )
    absolute = Path(os.path.abspath(os.fspath(raw)))
    if absolute in {Path(absolute.anchor), Path.home().resolve(strict=False)}:
        raise ScreenshotOperationError(
            "invalid_source_root", "The filesystem root and home folder cannot be watched."
        )
    if absolute.is_symlink():
        raise ScreenshotOperationError(
            "unsafe_source_root", "Screenshot folder cannot be a symbolic link."
        )
    try:
        metadata = absolute.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ScreenshotOperationError(
            "source_root_missing", "Configured screenshot folder does not exist."
        ) from exc
    except PermissionError as exc:
        raise ScreenshotOperationError(
            "permission_denied", "Configured screenshot folder is not accessible."
        ) from exc
    except OSError as exc:
        raise ScreenshotOperationError(
            "source_root_unavailable", "Configured screenshot folder cannot be inspected."
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ScreenshotOperationError(
            "invalid_source_root", "Configured screenshot path is not a directory."
        )
    resolved = absolute.resolve(strict=True)
    if any(_paths_overlap(resolved, root.resolve(strict=False)) for root in forbidden_roots):
        raise ScreenshotOperationError(
            "source_root_overlap",
            "Screenshot folder cannot overlap Froganize state or workspace folders.",
        )
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise ScreenshotOperationError(
            "permission_denied", "Configured screenshot folder is not readable and writable."
        )
    return resolved


def looks_like_screenshot(name: str) -> bool:
    """Match the same conservative system screenshot families as the Swift agent."""
    path = Path(name)
    extension = path.suffix.removeprefix(".").casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        return False
    return any(pattern.search(path.stem) is not None for pattern in SCREENSHOT_PATTERNS)


def _snapshot_from_stat(metadata: os.stat_result) -> ScreenshotSnapshot:
    return ScreenshotSnapshot(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
    )


def _snapshot_matches(snapshot: ScreenshotSnapshot, metadata: os.stat_result) -> bool:
    return snapshot == _snapshot_from_stat(metadata)


def _inspect_regular_file(path: Path, snapshot: ScreenshotSnapshot) -> None:
    if path.is_symlink():
        raise ScreenshotOperationError(
            "symbolic_link", "Screenshot source is a symbolic link and was skipped."
        )
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ScreenshotOperationError(
            "source_missing", "Screenshot disappeared before the rename."
        ) from exc
    except PermissionError as exc:
        raise ScreenshotOperationError(
            "permission_denied", "Screenshot is no longer readable."
        ) from exc
    except OSError as exc:
        raise ScreenshotOperationError(
            "source_unavailable", "Screenshot cannot be inspected safely."
        ) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ScreenshotOperationError(
            "unsupported_file_type", "Only regular screenshot files can be renamed."
        )
    if not _snapshot_matches(snapshot, metadata):
        raise ScreenshotOperationError(
            "source_changed", "Screenshot changed after AI analysis; it was not renamed."
        )
    if not os.access(path, os.R_OK | os.W_OK):
        raise ScreenshotOperationError(
            "permission_denied", "Screenshot is no longer readable and writable."
        )


def sanitize_title(raw_title: str) -> str:
    """Convert untrusted AI text into a bounded filename stem or fail closed."""
    value = unicodedata.normalize("NFKC", raw_title.strip())
    value = re.sub(r"\.(png|jpe?g|heic|webp)$", "", value, flags=re.IGNORECASE)
    mapped = []
    for character in value:
        category = unicodedata.category(character)
        if character in FORBIDDEN_FILENAME_CHARACTERS or category.startswith("C"):
            mapped.append(" ")
        else:
            mapped.append(character)
    value = "-".join("".join(mapped).split())
    value = value.strip("-_.，。；：、 ")
    value = value[:MAX_TITLE_CHARACTERS].rstrip("-_.，。；：、 ")
    if not value or value in {".", ".."}:
        raise ScreenshotOperationError(
            "invalid_filename", "AI title did not contain a safe filename."
        )
    return value


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    while value and len(value.encode("utf-8")) > maximum_bytes:
        value = value[:-1]
    return value.rstrip("-_. ")


def _occupied_names(directory: Path) -> set[str]:
    try:
        return {entry.name.casefold() for entry in directory.iterdir()}
    except PermissionError as exc:
        raise ScreenshotOperationError(
            "permission_denied", "Screenshot folder is not readable."
        ) from exc
    except OSError as exc:
        raise ScreenshotOperationError(
            "source_root_unavailable", "Screenshot folder cannot be scanned."
        ) from exc


def allocate_destination(
    source: Path,
    title: str,
    *,
    now: datetime,
) -> Path:
    """Calculate and reserve no path; execution rechecks immediately before rename."""
    sanitized = sanitize_title(title)
    extension = source.suffix.removeprefix(".").casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ScreenshotOperationError(
            "unsupported_file_type", "Screenshot extension is not supported."
        )
    timestamp = now.astimezone().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{timestamp}.{extension}"
    allowed_title_bytes = MAX_SAFE_FILENAME_BYTES - len(suffix.encode("utf-8"))
    sanitized = _truncate_utf8(sanitized, allowed_title_bytes)
    if not sanitized:
        raise ScreenshotOperationError(
            "invalid_filename", "AI title did not fit a safe filename."
        )
    stem = f"{sanitized}-{timestamp}"
    occupied = _occupied_names(source.parent)
    counter = 1
    while True:
        counter_suffix = "" if counter == 1 else f"-{counter}"
        name = f"{stem}{counter_suffix}.{extension}"
        if len(name.encode("utf-8")) > MAX_SAFE_FILENAME_BYTES:
            overflow = len(name.encode("utf-8")) - MAX_SAFE_FILENAME_BYTES
            shortened = _truncate_utf8(sanitized, len(sanitized.encode("utf-8")) - overflow)
            if not shortened:
                raise ScreenshotOperationError(
                    "invalid_filename", "No safe collision filename could be generated."
                )
            stem = f"{shortened}-{timestamp}"
            continue
        if name.casefold() not in occupied:
            return source.parent / name
        counter += 1


def _map_rename_error(exc: OSError) -> ScreenshotOperationError:
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return ScreenshotOperationError(
            "source_missing", "Screenshot disappeared before the rename."
        )
    if isinstance(exc, FileExistsError) or exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
        return ScreenshotOperationError(
            "target_conflict", "A destination filename became occupied; nothing was overwritten.",
            retryable=True,
        )
    if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
        return ScreenshotOperationError(
            "permission_denied", "The screenshot could not be renamed due to permissions."
        )
    if exc.errno == errno.ENOSPC:
        return ScreenshotOperationError(
            "insufficient_space", "The destination disk has insufficient free space."
        )
    if exc.errno in {errno.EBUSY, errno.ETXTBSY}:
        return ScreenshotOperationError(
            "source_busy", "The screenshot is currently in use.", retryable=True
        )
    return ScreenshotOperationError(
        "rename_failed", "The screenshot could not be renamed safely."
    )


def _journal_path(paths: IntelligencePaths, request_id: str) -> Path:
    return paths.pending / f"{request_id}.json"


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_journal(
    paths: IntelligencePaths,
    *,
    request_id: str,
    request_fingerprint_value: str,
    source_root: Path,
    source_name: str,
    target_name: str,
    snapshot: ScreenshotSnapshot,
    activity: ActivityRecord,
) -> Path:
    ensure_state_layout(paths)
    path = _journal_path(paths, request_id)
    if path.exists() or path.is_symlink():
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation with this request ID already exists."
        )
    payload = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "request_id": request_id,
        "request_fingerprint": request_fingerprint_value,
        "source_root": str(source_root),
        "source_name": source_name,
        "target_name": target_name,
        "snapshot": asdict(snapshot),
        "activity": asdict(activity),
    }
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=paths.pending,
            prefix=f".{request_id}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            os.chmod(temporary_name, 0o600)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_name, path)
        Path(temporary_name).unlink()
        temporary_name = None
        _sync_directory(paths.pending)
        return path
    except OSError as exc:
        raise ScreenshotOperationError(
            "journal_write_failed", "Could not prepare a recoverable rename operation."
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _delete_journal(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        _sync_directory(path.parent)
    except OSError as exc:
        raise ScreenshotOperationError(
            "journal_cleanup_failed", "The completed operation journal needs recovery."
        ) from exc


def _load_journal(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation journal is a symbolic link."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation journal is damaged."
        ) from exc
    expected = {
        "schema_version",
        "request_id",
        "request_fingerprint",
        "source_root",
        "source_name",
        "target_name",
        "snapshot",
        "activity",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw["schema_version"] != 1:
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation journal has invalid fields."
        )
    try:
        raw["activity"] = validate_activity_record(raw["activity"])
        raw["source_name"] = _safe_basename(raw["source_name"])
        raw["target_name"] = _safe_basename(raw["target_name"])
        raw["snapshot"] = ScreenshotSnapshot(**raw["snapshot"])
    except (TypeError, ScreenshotOperationError, IntelligenceStorageError) as exc:
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation journal is unsafe."
        ) from exc
    if (
        not isinstance(raw["source_root"], str)
        or not Path(raw["source_root"]).is_absolute()
        or raw["activity"].request_id != raw["request_id"]
        or raw["activity"].request_fingerprint != raw["request_fingerprint"]
        or Path(raw["activity"].source_root).resolve(strict=False)
        != Path(raw["source_root"]).resolve(strict=False)
        or raw["activity"].original_name
        not in {raw["source_name"], raw["target_name"]}
        or raw["activity"].renamed_name
        not in {raw["source_name"], raw["target_name"]}
        or raw["activity"].original_name == raw["activity"].renamed_name
        or raw["activity"].snapshot != asdict(raw["snapshot"])
    ):
        raise ScreenshotOperationError(
            "recovery_required", "A pending operation journal is inconsistent."
        )
    return raw


def _path_state(path: Path, snapshot: ScreenshotSnapshot) -> str:
    if path.is_symlink():
        return "unsafe"
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unsafe"
    if not stat.S_ISREG(metadata.st_mode) or not _snapshot_matches(snapshot, metadata):
        return "unsafe"
    return "matching"


def recover_pending_operations(
    paths: IntelligencePaths,
    records: tuple[ActivityRecord, ...],
    authorized_root: Path,
) -> None:
    """Conservatively settle journals left by a terminated helper process."""
    ensure_state_layout(paths)
    try:
        journals = sorted(paths.pending.glob("*.json"), key=lambda item: item.name)
    except OSError as exc:
        raise ScreenshotOperationError(
            "recovery_required", "Pending operation journals cannot be inspected."
        ) from exc
    for journal_path in journals:
        journal = _load_journal(journal_path)
        root = Path(journal["source_root"]).resolve(strict=False)
        if root != authorized_root.resolve(strict=False):
            raise ScreenshotOperationError(
                "recovery_required",
                "A pending operation journal is outside the authorized screenshot folder.",
            )
        source = root / journal["source_name"]
        target = root / journal["target_name"]
        snapshot = journal["snapshot"]
        source_state = _path_state(source, snapshot)
        target_state = _path_state(target, snapshot)
        committed = activity_for_request(records, journal["request_id"])
        if committed is not None:
            if committed.request_fingerprint != journal["request_fingerprint"]:
                raise ScreenshotOperationError(
                    "recovery_required", "Pending operation conflicts with committed activity."
                )
            if target_state == "matching" and source_state == "missing":
                _delete_journal(journal_path)
                continue
            if (
                committed.event_type == EVENT_UNDO
                and source_state == "missing"
                and target_state == "matching"
            ):
                _delete_journal(journal_path)
                continue
            raise ScreenshotOperationError(
                "recovery_required", "Committed activity no longer matches the filesystem."
            )

        if source_state == "matching" and target_state == "missing":
            _delete_journal(journal_path)
            continue
        if source_state == "missing" and target_state == "matching":
            try:
                if _casefold_name_is_occupied(source):
                    raise FileExistsError(errno.EEXIST, "original name occupied", source)
                _rename_no_replace(target, source)
            except OSError as exc:
                raise ScreenshotOperationError(
                    "recovery_required", "An interrupted rename could not be rolled back."
                ) from exc
            _delete_journal(journal_path)
            continue
        raise ScreenshotOperationError(
            "recovery_required", "An interrupted rename requires manual review."
        )


def _response_for_record(record: ActivityRecord) -> dict[str, Any]:
    if record.event_type == EVENT_RENAME:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": record.request_id,
            "status": "renamed",
            "event_id": record.event_id,
            "original_name": record.original_name,
            "renamed_name": record.renamed_name,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": record.request_id,
        "status": "undone",
        "event_id": record.event_id,
        "undo_of_event_id": record.undo_of_event_id,
        "renamed_name": record.renamed_name,
        "restored_name": record.original_name,
    }


def _existing_request_response(
    records: tuple[ActivityRecord, ...],
    *,
    request_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    existing = activity_for_request(records, request_id)
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise ScreenshotOperationError(
            "request_id_reused", "request_id was already used for a different request."
        )
    return _response_for_record(existing)


def _configured_response(request_id: str, root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": "configured",
        "screenshot_root": str(root),
    }


def _configure(
    request: ConfigureScreenshotRootRequest,
    paths: IntelligencePaths,
) -> dict[str, Any]:
    fingerprint = request_fingerprint(request)
    with MutationLock(paths):
        root = validate_screenshot_root(
            request.source_root,
            forbidden_roots=_managed_roots(paths),
        )
        try:
            existing = load_config(paths)
        except IntelligenceStorageError as exc:
            if exc.code != "configuration_missing":
                raise
        else:
            if existing.last_request_id == request.request_id:
                if existing.last_request_fingerprint != fingerprint:
                    raise ScreenshotOperationError(
                        "request_id_reused",
                        "request_id was already used for a different configuration.",
                    )
                return _configured_response(request.request_id, Path(existing.screenshot_root))
            old_root = validate_screenshot_root(
                existing.screenshot_root,
                forbidden_roots=_managed_roots(paths),
            )
            records = read_activity(paths)
            recover_pending_operations(paths, records, old_root)
        if any(paths.pending.glob("*.json")) and not paths.config.exists():
            raise ScreenshotOperationError(
                "recovery_required",
                "Pending operations must be reviewed before configuring a new folder.",
            )
        write_config(
            paths,
            screenshot_root=root,
            request_id=request.request_id,
            request_fingerprint=fingerprint,
        )
    return _configured_response(request.request_id, root)


def _rename(
    request: RenameScreenshotRequest,
    paths: IntelligencePaths,
    *,
    now: datetime,
) -> dict[str, Any]:
    source_name = _safe_basename(request.source_name)
    if not looks_like_screenshot(source_name):
        raise ScreenshotOperationError(
            "not_a_screenshot", "The requested file is not a recognized system screenshot."
        )
    if request.analysis.confidence < MINIMUM_CONFIDENCE:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request.request_id,
            "status": "skipped",
            "reason_code": "low_confidence",
            "reason": "AI confidence is below the automatic rename threshold.",
        }
    fingerprint = request_fingerprint(request)
    with MutationLock(paths):
        config = load_config(paths)
        source_root = validate_screenshot_root(
            config.screenshot_root,
            forbidden_roots=_managed_roots(paths),
        )
        records = read_activity(paths)
        recover_pending_operations(paths, records, source_root)
        records = read_activity(paths)
        duplicate = _existing_request_response(
            records, request_id=request.request_id, fingerprint=fingerprint
        )
        if duplicate is not None:
            return duplicate

        source = source_root / source_name
        if source.parent != source_root:
            raise ScreenshotOperationError(
                "source_outside_scope", "Screenshot is outside the authorized folder."
            )
        _inspect_regular_file(source, request.snapshot)
        title = (
            f"敏感截图-{request.analysis.category}"
            if request.analysis.sensitive
            else request.analysis.title
        )
        target = allocate_destination(source, title, now=now)
        record = new_rename_record(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            source_root=source_root,
            original_name=source.name,
            renamed_name=target.name,
            snapshot=request.snapshot,
            analysis=request.analysis,
            provider=request.provider,
            model=request.model,
        )
        journal = _write_journal(
            paths,
            request_id=request.request_id,
            request_fingerprint_value=fingerprint,
            source_root=source_root,
            source_name=source.name,
            target_name=target.name,
            snapshot=request.snapshot,
            activity=record,
        )
        moved = False
        try:
            _inspect_regular_file(source, request.snapshot)
            if _casefold_name_is_occupied(target):
                raise FileExistsError(errno.EEXIST, "destination occupied", target)
            _rename_no_replace(source, target)
            moved = True
            append_activity(paths, record)
        except IntelligenceStorageError:
            if moved:
                try:
                    if _casefold_name_is_occupied(source):
                        raise FileExistsError(errno.EEXIST, "original occupied", source)
                    _rename_no_replace(target, source)
                except OSError as rollback_error:
                    raise ScreenshotOperationError(
                        "recovery_required",
                        "Activity write failed and the rename could not be rolled back.",
                    ) from rollback_error
            _delete_journal(journal)
            raise
        except OSError as exc:
            _delete_journal(journal)
            raise _map_rename_error(exc) from exc
        except ScreenshotOperationError:
            _delete_journal(journal)
            raise
        _delete_journal(journal)
        return _response_for_record(record)


def _undo(
    request: UndoScreenshotRenameRequest,
    paths: IntelligencePaths,
) -> dict[str, Any]:
    fingerprint = request_fingerprint(request)
    with MutationLock(paths):
        config = load_config(paths)
        source_root = validate_screenshot_root(
            config.screenshot_root,
            forbidden_roots=_managed_roots(paths),
        )
        records = read_activity(paths)
        recover_pending_operations(paths, records, source_root)
        records = read_activity(paths)
        duplicate = _existing_request_response(
            records, request_id=request.request_id, fingerprint=fingerprint
        )
        if duplicate is not None:
            return duplicate

        original = outstanding_rename(records, request.event_id)
        if original is None:
            if request.event_id is None:
                return {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": request.request_id,
                    "status": "skipped",
                    "reason_code": "nothing_to_undo",
                    "reason": "There is no outstanding screenshot rename to undo.",
                }
            known = rename_by_event_id(records, request.event_id)
            if known is not None:
                return {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": request.request_id,
                    "status": "skipped",
                    "reason_code": "already_undone",
                    "reason": "This screenshot rename was already undone.",
                }
            raise ScreenshotOperationError(
                "event_not_found", "The requested screenshot rename event does not exist."
            )
        if Path(original.source_root).resolve(strict=False) != source_root:
            raise ScreenshotOperationError(
                "event_outside_scope",
                "The rename belongs to a screenshot folder that is no longer authorized.",
            )
        renamed_name = _safe_basename(original.renamed_name)
        original_name = _safe_basename(original.original_name)
        renamed = source_root / renamed_name
        restored = source_root / original_name
        snapshot = ScreenshotSnapshot(**original.snapshot)
        _inspect_regular_file(renamed, snapshot)
        if _casefold_name_is_occupied(restored):
            raise ScreenshotOperationError(
                "original_conflict", "The original screenshot name is occupied."
            )
        undo_record = new_undo_record(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            original=original,
        )
        journal = _write_journal(
            paths,
            request_id=request.request_id,
            request_fingerprint_value=fingerprint,
            source_root=source_root,
            source_name=renamed.name,
            target_name=restored.name,
            snapshot=snapshot,
            activity=undo_record,
        )
        moved = False
        try:
            _inspect_regular_file(renamed, snapshot)
            if _casefold_name_is_occupied(restored):
                raise FileExistsError(errno.EEXIST, "original name occupied", restored)
            _rename_no_replace(renamed, restored)
            moved = True
            append_activity(paths, undo_record)
        except IntelligenceStorageError:
            if moved:
                try:
                    if _casefold_name_is_occupied(renamed):
                        raise FileExistsError(errno.EEXIST, "renamed name occupied", renamed)
                    _rename_no_replace(restored, renamed)
                except OSError as rollback_error:
                    raise ScreenshotOperationError(
                        "recovery_required",
                        "Undo activity write failed and restoration could not be rolled back.",
                    ) from rollback_error
            _delete_journal(journal)
            raise
        except OSError as exc:
            _delete_journal(journal)
            raise _map_rename_error(exc) from exc
        except ScreenshotOperationError:
            _delete_journal(journal)
            raise
        _delete_journal(journal)
        return _response_for_record(undo_record)


def execute_request(
    request: IntelligenceRequest,
    paths: IntelligencePaths,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute one validated request without reading files outside its scope."""
    if isinstance(request, ConfigureScreenshotRootRequest):
        return _configure(request, paths)
    if isinstance(request, RenameScreenshotRequest):
        return _rename(request, paths, now=now or datetime.now().astimezone())
    if isinstance(request, UndoScreenshotRenameRequest):
        return _undo(request, paths)
    raise ScreenshotOperationError("unknown_action", "Unsupported Intelligence action.")
