"""Checked execution of move plans and safe batch undo."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from dropnest import planner
from dropnest.exceptions import HistoryError, WorkspaceSafetyError
from dropnest.history import (
    EVENT_SORT,
    EVENT_UNDO,
    RESULT_FAILED,
    RESULT_SUCCESS,
    append_history,
    latest_sort_records,
    new_batch_id,
    new_record,
    outstanding_latest_sort_records,
    read_history,
)
from dropnest.models import (
    BatchResult,
    ItemType,
    OperationResult,
    OperationStatus,
    PlanEntry,
    PlanLayout,
    PlanStatus,
    SortPlan,
    Workspace,
)
from dropnest.workspace import (
    WorkspaceLock,
    validate_desktop_source,
    validate_workspace,
)

BeforeEach = Callable[[PlanEntry], None]


def _raise_os_error(result: int, destination: Path) -> None:
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), destination)


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Move without replacing an exact occupied target where the OS supports it."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(source), os.fsencode(destination), 0x00000004)
        _raise_os_error(result, destination)
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is not None:
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                -100,
                os.fsencode(source),
                -100,
                os.fsencode(destination),
                1,
            )
            _raise_os_error(result, destination)
            return
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(errno.EEXIST, "destination already exists", destination)
    os.rename(source, destination)


def _casefold_name_is_occupied(destination: Path) -> bool:
    parent = destination.parent
    if not parent.exists():
        return False
    folded = destination.name.casefold()
    return any(child.name.casefold() == folded for child in parent.iterdir())


def _ensure_directory(path: Path, workspace: Workspace) -> None:
    if path.is_symlink():
        raise WorkspaceSafetyError(f"Archive directory cannot be a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"Archive path is not a directory: {path}")
    else:
        path.mkdir()
    if path.is_symlink():
        raise WorkspaceSafetyError(f"Archive directory became a symlink: {path}")
    try:
        path.resolve().relative_to(workspace.timeline.resolve())
    except ValueError as exc:
        raise WorkspaceSafetyError(f"Archive directory escapes Timeline: {path}") from exc


def _ensure_target_directory(
    entry: PlanEntry,
    workspace: Workspace,
    layout: PlanLayout,
    destination_root: Path,
) -> None:
    target_directory = entry.target_directory
    if target_directory is None:
        raise WorkspaceSafetyError("Planned entry has no target directory.")
    if entry.target is None or entry.target.parent != target_directory:
        raise WorkspaceSafetyError("Planned target does not match its target directory.")
    if destination_root.resolve() != workspace.timeline.resolve():
        raise WorkspaceSafetyError("Plan destination root does not match Timeline.")
    if layout is PlanLayout.MONTHLY:
        if target_directory.parent.parent != destination_root:
            raise WorkspaceSafetyError(
                "Target does not use the required year/month layout: "
                f"{target_directory}"
            )
        expected_year = f"{entry.year:04d}" if entry.year is not None else None
        expected_month = (
            f"{entry.year:04d}-{entry.month:02d}"
            if entry.year is not None and entry.month is not None
            else None
        )
        if (
            target_directory.parent.name != expected_year
            or target_directory.name != expected_month
        ):
            raise WorkspaceSafetyError(
                f"Target does not match the planned year/month: {target_directory}"
            )
        _ensure_directory(target_directory.parent, workspace)
        _ensure_directory(target_directory, workspace)
        return
    if layout is PlanLayout.COLLECTION_BATCH:
        if target_directory.parent != destination_root:
            raise WorkspaceSafetyError(
                f"Collection batch must be a direct Timeline child: {target_directory}"
            )
        if not target_directory.exists() or not target_directory.is_dir():
            raise WorkspaceSafetyError(
                f"Collection batch directory is not ready: {target_directory}"
            )
        if target_directory.is_symlink():
            raise WorkspaceSafetyError(
                f"Collection batch directory cannot be a symlink: {target_directory}"
            )
        return
    raise WorkspaceSafetyError(f"Unsupported plan layout: {layout}")


def _create_collection_batch_directory(
    plan: SortPlan,
    workspace: Workspace,
) -> Path | None:
    """Atomically create the one shared batch folder before moving anything."""
    planned = [entry for entry in plan.entries if entry.status is PlanStatus.PLANNED]
    if not planned:
        return None
    directories = {entry.target_directory for entry in planned}
    if None in directories or len(directories) != 1:
        raise WorkspaceSafetyError(
            "Collection plan entries must share one batch directory."
        )
    target_directory = next(iter(directories))
    assert target_directory is not None
    destination_root = plan.destination_root
    if destination_root.resolve() != workspace.timeline.resolve():
        raise WorkspaceSafetyError("Plan destination root does not match Timeline.")
    if target_directory.parent != destination_root:
        raise WorkspaceSafetyError(
            f"Collection batch must be a direct Timeline child: {target_directory}"
        )
    if target_directory.is_symlink() or target_directory.exists():
        raise FileExistsError(
            errno.EEXIST,
            "planned collection batch is occupied",
            target_directory,
        )
    for entry in planned:
        if entry.target is None or entry.target.parent != target_directory:
            raise WorkspaceSafetyError(
                "Collection target does not match its shared batch directory."
            )
    target_directory.mkdir()
    if target_directory.is_symlink() or not target_directory.is_dir():
        raise WorkspaceSafetyError(
            f"Collection batch directory is unsafe: {target_directory}"
        )
    try:
        target_directory.resolve().relative_to(destination_root.resolve())
    except ValueError as exc:
        raise WorkspaceSafetyError(
            f"Collection batch escapes Timeline: {target_directory}"
        ) from exc
    return target_directory


def _validate_planned_entry(
    entry: PlanEntry,
    workspace: Workspace,
    source_root: Path,
) -> os.stat_result:
    if (
        entry.status is not PlanStatus.PLANNED
        or entry.target is None
        or entry.snapshot is None
        or entry.item_type is None
    ):
        raise WorkspaceSafetyError("Executor received an incomplete planned entry.")
    if entry.source.parent.resolve() != source_root.resolve():
        raise WorkspaceSafetyError(
            f"Source is not a direct source child: {entry.source}"
        )
    if entry.source.is_symlink():
        raise WorkspaceSafetyError(f"Source became a symbolic link: {entry.source}")
    try:
        metadata = entry.source.stat(follow_symlinks=False)
    except FileNotFoundError:
        raise FileNotFoundError(f"Source disappeared: {entry.source}") from None
    if not planner.snapshot_matches(entry.snapshot, metadata, entry.source):
        raise OSError(f"Source changed after planning: {entry.source}")
    expected_directory = entry.item_type is ItemType.DIRECTORY
    type_matches = (
        stat.S_ISDIR(metadata.st_mode)
        if expected_directory
        else stat.S_ISREG(metadata.st_mode)
    )
    if not type_matches:
        raise OSError(f"Source type changed after planning: {entry.source}")
    required_access = os.R_OK | (os.X_OK if expected_directory else 0)
    if not os.access(entry.source, required_access):
        raise PermissionError(f"Source is no longer readable: {entry.source}")
    try:
        entry.target.parent.resolve(strict=False).relative_to(
            workspace.timeline.resolve()
        )
    except ValueError as exc:
        raise WorkspaceSafetyError(
            f"Target escapes Timeline: {entry.target}"
        ) from exc
    try:
        entry.target.resolve(strict=False).relative_to(entry.source.resolve())
    except ValueError:
        pass
    else:
        raise WorkspaceSafetyError(
            f"Cannot move an item inside itself: {entry.source}"
        )
    return metadata


def _failure_reason(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, FileNotFoundError):
        return "source_missing", str(exc)
    if isinstance(exc, FileExistsError) or getattr(exc, "errno", None) in {
        errno.EEXIST,
        errno.ENOTEMPTY,
    }:
        return "target_conflict", f"planned target is occupied: {exc}"
    if isinstance(exc, PermissionError):
        return "permission_denied", str(exc)
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return "insufficient_space", str(exc)
    if getattr(exc, "errno", None) in {errno.EBUSY, errno.ETXTBSY}:
        return "source_busy", str(exc)
    if "changed after planning" in str(exc):
        return "source_changed", str(exc)
    if isinstance(exc, WorkspaceSafetyError):
        return "safety_error", str(exc)
    return "move_failed", str(exc)


def execute_plan(
    plan: SortPlan,
    *,
    before_each: BeforeEach | None = None,
    source_root: Path | None = None,
) -> BatchResult:
    """Execute a plan without recalculating any destination decision."""
    expected_source = (source_root or plan.workspace.inbox).resolve()
    if plan.source_root.resolve() != expected_source:
        raise WorkspaceSafetyError(
            "Plan source does not match the authorized source directory."
        )
    is_inbox_plan = expected_source == plan.workspace.inbox.resolve()
    workspace = validate_workspace(
        plan.workspace.root,
        require_writable=True,
        require_inbox=is_inbox_plan,
    )
    if plan.destination_root.resolve() != workspace.timeline.resolve():
        raise WorkspaceSafetyError(
            "Plan destination root does not match the authorized Timeline."
        )
    history_source_roots: tuple[Path, ...] = ()
    if not is_inbox_plan:
        expected_source = validate_desktop_source(
            expected_source,
            workspace,
            require_writable=True,
        )
        history_source_roots = (expected_source,)
    read_history(workspace, source_roots=history_source_roots)
    batch_directory = None
    if plan.layout is PlanLayout.COLLECTION_BATCH:
        batch_directory = _create_collection_batch_directory(plan, workspace)
        if batch_directory is None:
            results = tuple(
                OperationResult(
                    entry.source,
                    entry.target,
                    OperationStatus.SKIPPED
                    if entry.status is PlanStatus.SKIPPED
                    else OperationStatus.FAILED,
                    entry.reason_code,
                    entry.reason,
                )
                for entry in plan.entries
            )
            return BatchResult(None, results)
    batch_id = new_batch_id()
    results: list[OperationResult] = []
    for entry in plan.entries:
        if entry.status is PlanStatus.SKIPPED:
            results.append(
                OperationResult(
                    entry.source,
                    entry.target,
                    OperationStatus.SKIPPED,
                    entry.reason_code,
                    entry.reason,
                )
            )
            continue
        if entry.status is PlanStatus.FAILED:
            results.append(
                OperationResult(
                    entry.source,
                    entry.target,
                    OperationStatus.FAILED,
                    entry.reason_code,
                    entry.reason,
                )
            )
            continue
        if before_each is not None:
            before_each(entry)
        try:
            _validate_planned_entry(entry, workspace, expected_source)
            _ensure_target_directory(
                entry,
                workspace,
                plan.layout,
                plan.destination_root,
            )
            assert entry.target is not None
            if _casefold_name_is_occupied(entry.target):
                raise FileExistsError(
                    errno.EEXIST,
                    "destination name is occupied case-insensitively",
                    entry.target,
                )
            _rename_no_replace(entry.source, entry.target)
            assert entry.item_type is not None
            assert entry.classification_time is not None
            record = new_record(
                batch_id=batch_id,
                event_type=EVENT_SORT,
                source=entry.source,
                destination=entry.target,
                item_type=entry.item_type,
                classification_time=entry.classification_time.isoformat(),
                result=RESULT_SUCCESS,
            )
            try:
                append_history(
                    workspace,
                    record,
                    source_roots=history_source_roots,
                )
            except HistoryError:
                try:
                    _rename_no_replace(entry.target, entry.source)
                except OSError as rollback_error:
                    raise HistoryError(
                        "History write failed after moving an item and automatic "
                        f"rollback also failed ({entry.target} -> {entry.source}): "
                        f"{rollback_error}"
                    ) from rollback_error
                raise
        except (OSError, WorkspaceSafetyError) as exc:
            code, reason = _failure_reason(exc)
            results.append(
                OperationResult(
                    entry.source,
                    entry.target,
                    OperationStatus.FAILED,
                    code,
                    reason,
                )
            )
            continue
        results.append(
            OperationResult(entry.source, entry.target, OperationStatus.MOVED)
        )
    if batch_directory is not None and not any(
        result.status is OperationStatus.MOVED for result in results
    ):
        try:
            batch_directory.rmdir()
        except OSError:
            pass
    return BatchResult(batch_id, tuple(results))


def sort_workspace(
    workspace_path: str | os.PathLike[str],
    *,
    before_each: BeforeEach | None = None,
) -> tuple[SortPlan, BatchResult]:
    """Lock, freshly plan, and execute one workspace sort."""
    workspace = validate_workspace(workspace_path, require_writable=True)
    with WorkspaceLock(workspace):
        fresh_plan = planner.build_plan(workspace.root)
        result = execute_plan(fresh_plan, before_each=before_each)
    return fresh_plan, result


def collect_desktop(
    workspace_path: str | os.PathLike[str],
    *,
    desktop_path: str | os.PathLike[str] | None = None,
    collected_at: datetime | None = None,
    before_each: BeforeEach | None = None,
) -> tuple[SortPlan, BatchResult]:
    """Collect safe Desktop children by modification month in one undo batch."""
    workspace = validate_workspace(
        workspace_path,
        require_writable=True,
        require_inbox=False,
    )
    requested_desktop = Path(desktop_path or (Path.home() / "Desktop"))
    desktop = validate_desktop_source(
        requested_desktop,
        workspace,
        require_writable=True,
    )
    with WorkspaceLock(workspace):
        fresh_plan = planner.build_desktop_collection_plan(
            workspace.root,
            desktop_path=desktop,
            collected_at=collected_at,
        )
        result = execute_plan(
            fresh_plan,
            before_each=before_each,
            source_root=desktop,
        )
    return fresh_plan, result


def execute_selected_plan(
    plan: SortPlan,
    selected_names: tuple[str, ...],
    *,
    before_each: BeforeEach | None = None,
) -> BatchResult:
    """Execute only explicitly selected safe entries from one saved plan."""
    if not selected_names:
        raise ValueError("Select at least one Desktop item to archive.")
    if len(selected_names) != len(set(selected_names)):
        raise ValueError("Selected Desktop item names must be unique.")
    by_name = {entry.source.name: entry for entry in plan.entries}
    selected: list[PlanEntry] = []
    for name in selected_names:
        entry = by_name.get(name)
        if entry is None:
            raise ValueError(f"Selected Desktop item is not in this assessment: {name}")
        if entry.status is not PlanStatus.PLANNED:
            raise ValueError(f"Selected Desktop item cannot be archived safely: {name}")
        selected.append(entry)
    selected_plan = replace(plan, entries=tuple(selected))
    with WorkspaceLock(plan.workspace):
        return execute_plan(
            selected_plan,
            before_each=before_each,
            source_root=plan.source_root,
        )


def _safe_history_path(path_text: str, parent: Path, label: str) -> Path:
    path = Path(path_text)
    if path.parent != parent:
        raise HistoryError(f"History {label} is outside the expected directory: {path}")
    return path


def undo_workspace(
    workspace_path: str | os.PathLike[str],
    *,
    source_root: str | os.PathLike[str] | None = None,
    expected_batch_id: str | None = None,
) -> BatchResult:
    """Restore outstanding operations from the latest sort batch only."""
    if expected_batch_id is not None:
        try:
            uuid.UUID(expected_batch_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryError("Expected undo batch ID is invalid.") from exc
    workspace = validate_workspace(
        workspace_path,
        require_writable=True,
        require_inbox=source_root is None,
    )
    history_source_roots: tuple[Path, ...] = ()
    active_source_root = workspace.inbox
    if source_root is not None:
        desktop = validate_desktop_source(
            source_root,
            workspace,
            require_writable=True,
        )
        history_source_roots = (desktop,)
        active_source_root = desktop
    with WorkspaceLock(workspace):
        records = read_history(workspace, source_roots=history_source_roots)
        latest = latest_sort_records(records, source_root=active_source_root)
        if expected_batch_id is not None and (
            not latest or latest[0].batch_id != expected_batch_id
        ):
            raise HistoryError(
                "The organization history changed after the calendar was opened. "
                "Refresh the calendar before undoing."
            )
        outstanding = outstanding_latest_sort_records(
            records,
            source_root=active_source_root,
        )
        if not latest or not outstanding:
            return BatchResult(None, ())

        undo_batch_id = new_batch_id()
        results: list[OperationResult] = []
        batch_directories: set[Path] = set()
        for original in reversed(outstanding):
            archived = _safe_history_path(
                original.destination_path,
                Path(original.destination_path).parent,
                "destination",
            )
            restored = Path(original.source_path)
            item_type = ItemType(original.item_type)
            try:
                archived.relative_to(workspace.timeline)
            except ValueError as exc:
                raise HistoryError(
                    f"History destination is outside Timeline: {archived}"
                ) from exc
            if archived.parent.parent == workspace.timeline:
                batch_directories.add(archived.parent)

            failure: tuple[str, str] | None = None
            if archived.is_symlink():
                failure = ("symbolic_link", "archived item is now a symbolic link")
            elif not archived.exists():
                failure = ("target_missing", f"archived item does not exist: {archived}")
            elif (
                (item_type is ItemType.DIRECTORY and not archived.is_dir())
                or (item_type is ItemType.FILE and not archived.is_file())
            ):
                failure = (
                    "type_changed",
                    f"archived item type no longer matches history: {archived}",
                )
            elif _casefold_name_is_occupied(restored):
                failure = (
                    "original_conflict",
                    f"original path is occupied: {restored}",
                )
            else:
                try:
                    _rename_no_replace(archived, restored)
                except OSError as exc:
                    failure = _failure_reason(exc)

            result_value = RESULT_FAILED if failure else RESULT_SUCCESS
            try:
                undo_record = new_record(
                    batch_id=undo_batch_id,
                    event_type=EVENT_UNDO,
                    source=archived,
                    destination=restored,
                    item_type=item_type,
                    classification_time=original.classification_time,
                    result=result_value,
                    undo_of_event_id=original.event_id,
                )
                append_history(
                    workspace,
                    undo_record,
                    source_roots=history_source_roots,
                )
            except HistoryError:
                if failure is None:
                    try:
                        _rename_no_replace(restored, archived)
                    except OSError as rollback_error:
                        raise HistoryError(
                            "Undo history write failed after restoring an item and "
                            "automatic rollback also failed "
                            f"({restored} -> {archived}): {rollback_error}"
                        ) from rollback_error
                raise
            if failure:
                results.append(
                    OperationResult(
                        archived,
                        restored,
                        OperationStatus.FAILED,
                        failure[0],
                        failure[1],
                    )
                )
            else:
                results.append(
                    OperationResult(
                        archived,
                        restored,
                        OperationStatus.RESTORED,
                    )
                )
        for directory in batch_directories:
            if directory.is_symlink() or directory.parent != workspace.timeline:
                continue
            try:
                directory.rmdir()
            except OSError:
                pass
        return BatchResult(undo_batch_id, tuple(results))
