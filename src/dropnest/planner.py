"""Read-only source scanning, Desktop evaluation, and deterministic planning."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dropnest.conflict import available_name
from dropnest.exceptions import PlanningError, WorkspaceSafetyError
from dropnest.models import (
    AssessmentEntry,
    DesktopAssessment,
    EvaluationGroup,
    ItemSnapshot,
    ItemType,
    PlanEntry,
    PlanLayout,
    PlanStatus,
    SortPlan,
    Workspace,
)
from dropnest.workspace import validate_desktop_source, validate_workspace

TimePolicy = Callable[[os.stat_result], datetime]
MAX_DIRECTORY_ITEMS = 50_000
RECENT_DAYS = 7
ARCHIVE_AFTER_DAYS = RECENT_DAYS
DESKTOP_LAUNCHER_NAMES = frozenset(
    {"DropNest.app", "Froganize.app", "整理桌面.app"}
)
DESKTOP_LAUNCHER_NAMES_CASEFOLDED = frozenset(
    name.casefold() for name in DESKTOP_LAUNCHER_NAMES
)
CLEANUP_PARTIAL_DOWNLOAD_SUFFIXES = (
    ".crdownload",
    ".download",
    ".part",
)


def _is_protected_desktop_application(path: Path) -> bool:
    """Leave application bundles on the Desktop, even after they are renamed."""
    lowered = path.name.casefold()
    return (
        lowered in DESKTOP_LAUNCHER_NAMES_CASEFOLDED
        or lowered.endswith(".app")
    )


def modification_time_policy(metadata: os.stat_result) -> datetime:
    """Convert st_mtime to an aware datetime in the current local timezone."""
    return datetime.fromtimestamp(metadata.st_mtime).astimezone()


def _skip_reason(path: Path, metadata: os.stat_result | None) -> tuple[str, str] | None:
    name = path.name
    lowered = name.casefold()
    if path.is_symlink():
        return "symbolic_link", "symbolic links are skipped"
    if name in {".DS_Store", ".gitkeep"}:
        return "hidden", f"{name} is a reserved hidden item"
    if name.startswith("."):
        return "hidden", "hidden items are skipped"
    if name.startswith("~"):
        return "temporary", "temporary names beginning with '~' are skipped"
    if metadata is not None and stat.S_ISREG(metadata.st_mode):
        if lowered.endswith(".tmp"):
            return "temporary", "files ending in .tmp are skipped"
        if lowered.endswith(".icloud"):
            return "cloud_placeholder", "iCloud placeholder files are skipped"
    return None


def cleanup_reason(
    path: Path,
    metadata: os.stat_result,
) -> tuple[str, str] | None:
    """Return a conservative cleanup recommendation for a regular file."""
    if not stat.S_ISREG(metadata.st_mode):
        return None
    name = path.name
    lowered = name.casefold()
    if lowered == ".ds_store":
        return "cleanup_system_junk", "macOS Desktop metadata can be regenerated"
    if name.startswith("."):
        return None
    if name.startswith("~"):
        return "cleanup_temporary", "temporary names beginning with '~'"
    if lowered.endswith(".tmp"):
        return "cleanup_temporary", "temporary files ending in .tmp"
    if lowered.endswith(CLEANUP_PARTIAL_DOWNLOAD_SUFFIXES):
        return "cleanup_partial_download", "incomplete download residue"
    return None


def _snapshot(
    metadata: os.stat_result,
    *,
    tree_digest: str | None = None,
) -> ItemSnapshot:
    return ItemSnapshot(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        tree_digest=tree_digest,
    )


def _update_tree_digest(
    digest: Any,
    relative: Path,
    metadata: os.stat_result,
) -> None:
    values = (
        relative.as_posix(),
        str(metadata.st_dev),
        str(metadata.st_ino),
        str(metadata.st_mode),
        str(metadata.st_size),
        str(metadata.st_mtime_ns),
    )
    digest.update("\0".join(values).encode("utf-8", errors="surrogateescape"))
    digest.update(b"\0")


def _directory_tree_metadata(path: Path) -> tuple[int, str]:
    """Return latest descendant mtime and a metadata-only tree fingerprint."""
    try:
        root_metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PlanningError(f"Cannot inspect folder metadata: {path}") from exc
    latest_mtime_ns = root_metadata.st_mtime_ns
    digest = hashlib.sha256()
    _update_tree_digest(digest, Path("."), root_metadata)
    pending: list[tuple[Path, Path]] = [(path, Path("."))]
    inspected_count = 0

    while pending:
        directory, relative_directory = pending.pop()
        if not os.access(directory, os.R_OK | os.X_OK):
            raise PlanningError(f"Folder content is not readable: {directory}")
        try:
            with os.scandir(directory) as iterator:
                children = sorted(
                    tuple(iterator),
                    key=lambda child: (child.name.casefold(), child.name),
                )
        except PermissionError as exc:
            raise PlanningError(
                f"Folder content is not readable: {directory}"
            ) from exc
        except OSError as exc:
            raise PlanningError(f"Cannot inspect folder content: {directory}") from exc

        for child in children:
            inspected_count += 1
            if inspected_count > MAX_DIRECTORY_ITEMS:
                raise PlanningError(
                    "Folder contains more than "
                    f"{MAX_DIRECTORY_ITEMS:,} items and is too large to assess safely."
                )
            child_path = Path(child.path)
            relative = relative_directory / child.name
            try:
                metadata = child.stat(follow_symlinks=False)
            except PermissionError as exc:
                raise PlanningError(
                    f"Folder contains an unreadable item: {child_path}"
                ) from exc
            except OSError as exc:
                raise PlanningError(
                    f"Cannot inspect folder item: {child_path}"
                ) from exc
            latest_mtime_ns = max(latest_mtime_ns, metadata.st_mtime_ns)
            _update_tree_digest(digest, relative, metadata)

            if stat.S_ISLNK(metadata.st_mode):
                continue
            if stat.S_ISDIR(metadata.st_mode):
                pending.append((child_path, relative))
                continue
            if stat.S_ISREG(metadata.st_mode):
                if child.name.casefold().endswith(".icloud"):
                    raise PlanningError(
                        f"Folder contains an iCloud placeholder: {child_path}"
                    )
                continue
            raise PlanningError(
                f"Folder contains an unsupported item type: {child_path}"
            )
    return latest_mtime_ns, digest.hexdigest()


def snapshot_matches(
    snapshot: ItemSnapshot,
    metadata: os.stat_result,
    source: Path | None = None,
) -> bool:
    """Return whether current source metadata still matches a plan snapshot."""
    if snapshot.tree_digest is None:
        return snapshot == _snapshot(metadata)
    if source is None or not stat.S_ISDIR(metadata.st_mode):
        return False
    try:
        _latest_mtime_ns, tree_digest = _directory_tree_metadata(source)
    except PlanningError:
        return False
    return snapshot == _snapshot(metadata, tree_digest=tree_digest)


def _destination_is_contained(workspace: Workspace, destination: Path) -> bool:
    try:
        destination.resolve(strict=False).relative_to(workspace.timeline.resolve())
    except ValueError:
        return False
    return True


def _existing_occupied_names(
    workspace: Workspace,
    target_directory: Path,
) -> set[str]:
    """Read existing names without creating the planned directory."""
    year_directory = target_directory.parent
    for label, path in (("year", year_directory), ("month", target_directory)):
        if path.is_symlink():
            raise WorkspaceSafetyError(
                f"Timeline {label} path cannot be a symbolic link: {path}"
            )
        if path.exists() and not path.is_dir():
            raise PlanningError(
                f"Timeline {label} path is not a directory: {path}"
            )
    if not _destination_is_contained(workspace, target_directory):
        raise WorkspaceSafetyError(
            f"Planned destination escapes Timeline: {target_directory}"
        )
    if not target_directory.exists():
        return set()
    try:
        return {child.name.casefold() for child in target_directory.iterdir()}
    except PermissionError as exc:
        raise PlanningError(
            f"Timeline destination is not readable: {target_directory}"
        ) from exc
    except OSError as exc:
        raise PlanningError(
            f"Cannot inspect Timeline destination: {target_directory}"
        ) from exc


def _inspect_item(path: Path) -> tuple[os.stat_result | None, PlanEntry | None]:
    """Return metadata or an explicit non-planned entry."""
    if path.is_symlink():
        code, reason = _skip_reason(path, None) or (
            "symbolic_link",
            "symbolic links are skipped",
        )
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.SKIPPED,
            reason_code=code,
            reason=reason,
        )
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.FAILED,
            reason_code="source_missing",
            reason="source disappeared while planning",
        )
    except PermissionError:
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.SKIPPED,
            reason_code="unreadable",
            reason="item metadata is not readable",
        )
    except OSError as exc:
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.FAILED,
            reason_code="inspection_failed",
            reason=f"cannot inspect item: {exc}",
        )

    reason = _skip_reason(path, metadata)
    if reason is not None:
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.SKIPPED,
            reason_code=reason[0],
            reason=reason[1],
            snapshot=_snapshot(metadata),
        )
    required_access = os.R_OK
    if stat.S_ISDIR(metadata.st_mode):
        required_access |= os.X_OK
    if not os.access(path, required_access):
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.SKIPPED,
            reason_code="unreadable",
            reason="item is not readable",
            snapshot=_snapshot(metadata),
        )
    if stat.S_ISREG(metadata.st_mode):
        item_type = ItemType.FILE
    elif stat.S_ISDIR(metadata.st_mode):
        item_type = ItemType.DIRECTORY
    else:
        return None, PlanEntry(
            source=path,
            item_type=None,
            status=PlanStatus.SKIPPED,
            reason_code="unsupported_type",
            reason="only regular files and directories are supported",
            snapshot=_snapshot(metadata),
        )
    return metadata, PlanEntry(
        source=path,
        item_type=item_type,
        status=PlanStatus.PLANNED,
        snapshot=_snapshot(metadata),
    )


def build_plan(
    workspace_path: str | os.PathLike[str],
    *,
    time_policy: TimePolicy = modification_time_policy,
) -> SortPlan:
    """Build a deterministic, read-only plan for one validated workspace."""
    workspace = validate_workspace(workspace_path)
    try:
        children = sorted(
            workspace.inbox.iterdir(),
            key=lambda path: (path.name.casefold(), path.name),
        )
    except PermissionError as exc:
        raise PlanningError(f"Inbox is not readable: {workspace.inbox}") from exc
    except OSError as exc:
        raise PlanningError(f"Cannot scan Inbox: {workspace.inbox}") from exc

    occupied_by_directory: dict[Path, set[str]] = {}
    entries: list[PlanEntry] = []
    for source in children:
        metadata, inspected = _inspect_item(source)
        assert inspected is not None
        if metadata is None or inspected.status is not PlanStatus.PLANNED:
            entries.append(inspected)
            continue

        try:
            classification_time = time_policy(metadata)
            if classification_time.tzinfo is None:
                classification_time = classification_time.astimezone()
            year = classification_time.year
            month = classification_time.month
            target_directory = (
                workspace.timeline / f"{year:04d}" / f"{year:04d}-{month:02d}"
            )
            occupied = occupied_by_directory.get(target_directory)
            if occupied is None:
                occupied = _existing_occupied_names(workspace, target_directory)
                occupied_by_directory[target_directory] = occupied
            target_name, renamed = available_name(
                source.name,
                inspected.item_type,
                occupied,
            )
        except WorkspaceSafetyError:
            raise
        except (OSError, OverflowError, ValueError, PlanningError) as exc:
            entries.append(
                PlanEntry(
                    source=source,
                    item_type=inspected.item_type,
                    status=PlanStatus.FAILED,
                    snapshot=inspected.snapshot,
                    reason_code="planning_failed",
                    reason=str(exc),
                )
            )
            continue

        entries.append(
            PlanEntry(
                source=source,
                item_type=inspected.item_type,
                status=PlanStatus.PLANNED,
                target_directory=target_directory,
                target=target_directory / target_name,
                classification_time=classification_time,
                year=year,
                month=month,
                snapshot=inspected.snapshot,
                renamed_from=source.name if renamed else None,
            )
        )

    return SortPlan(
        workspace=workspace,
        source_root=workspace.inbox,
        destination_root=workspace.timeline,
        layout=PlanLayout.MONTHLY,
        generated_at=datetime.now(UTC),
        entries=tuple(entries),
    )


def _evaluation_group(
    classification_time: datetime,
    now: datetime,
) -> tuple[EvaluationGroup, int]:
    elapsed = now - classification_time.astimezone(now.tzinfo)
    age_days = max(0, int(elapsed.total_seconds() // timedelta(days=1).total_seconds()))
    if age_days <= ARCHIVE_AFTER_DAYS:
        return EvaluationGroup.RECENT, age_days
    return EvaluationGroup.ARCHIVE, age_days


def build_desktop_assessment(
    workspace_path: str | os.PathLike[str],
    *,
    desktop_path: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
    time_policy: TimePolicy = modification_time_policy,
) -> DesktopAssessment:
    """Evaluate only direct Desktop children and plan safe whole-item moves."""
    workspace = validate_workspace(workspace_path, require_inbox=False)
    requested_desktop = Path(desktop_path or (Path.home() / "Desktop"))
    desktop = validate_desktop_source(requested_desktop, workspace)
    reference_time = now or datetime.now().astimezone()
    if reference_time.tzinfo is None:
        reference_time = reference_time.astimezone()
    try:
        children = sorted(
            (
                path
                for path in desktop.iterdir()
                if not _is_protected_desktop_application(path)
            ),
            key=lambda path: (path.name.casefold(), path.name),
        )
    except PermissionError as exc:
        raise PlanningError(f"Desktop is not readable: {desktop}") from exc
    except OSError as exc:
        raise PlanningError(f"Cannot scan Desktop: {desktop}") from exc

    occupied_by_directory: dict[Path, set[str]] = {}
    plan_entries: list[PlanEntry] = []
    assessment_entries: list[AssessmentEntry] = []
    for source in children:
        if not source.is_symlink():
            try:
                cleanup_metadata = source.stat(follow_symlinks=False)
                recommendation = cleanup_reason(source, cleanup_metadata)
                cleanup_time = time_policy(cleanup_metadata)
                if cleanup_time.tzinfo is None:
                    cleanup_time = cleanup_time.astimezone()
            except (OSError, OverflowError, ValueError):
                recommendation = None
            if recommendation is not None:
                cleanup_entry = PlanEntry(
                    source=source,
                    item_type=ItemType.FILE,
                    status=PlanStatus.SKIPPED,
                    classification_time=cleanup_time,
                    snapshot=_snapshot(cleanup_metadata),
                    reason_code=recommendation[0],
                    reason=recommendation[1],
                )
                _unused_group, age_days = _evaluation_group(
                    cleanup_time,
                    reference_time,
                )
                plan_entries.append(cleanup_entry)
                assessment_entries.append(
                    AssessmentEntry(
                        plan_entry=cleanup_entry,
                        group=EvaluationGroup.CLEANUP,
                        age_days=age_days,
                        default_selected=False,
                    )
                )
                continue

        metadata, inspected = _inspect_item(source)
        assert inspected is not None
        if metadata is None or inspected.status is not PlanStatus.PLANNED:
            plan_entries.append(inspected)
            assessment_entries.append(
                AssessmentEntry(
                    plan_entry=inspected,
                    group=EvaluationGroup.UNSAFE,
                    age_days=None,
                    default_selected=False,
                )
            )
            continue

        if source.name.casefold().endswith(CLEANUP_PARTIAL_DOWNLOAD_SUFFIXES):
            try:
                partial_time = time_policy(metadata)
                if partial_time.tzinfo is None:
                    partial_time = partial_time.astimezone()
            except (OSError, OverflowError, ValueError):
                partial_time = None
            partial_entry = PlanEntry(
                source=source,
                item_type=inspected.item_type,
                status=PlanStatus.SKIPPED,
                classification_time=partial_time,
                snapshot=inspected.snapshot,
                reason_code="cleanup_partial_download",
                reason="incomplete download residue",
            )
            plan_entries.append(partial_entry)
            assessment_entries.append(
                AssessmentEntry(
                    plan_entry=partial_entry,
                    group=EvaluationGroup.UNSAFE,
                    age_days=None,
                    default_selected=False,
                )
            )
            continue

        classification_time: datetime
        snapshot = inspected.snapshot
        if inspected.item_type is ItemType.DIRECTORY:
            try:
                latest_mtime_ns, tree_digest = _directory_tree_metadata(source)
            except PlanningError as exc:
                unsafe = PlanEntry(
                    source=source,
                    item_type=ItemType.DIRECTORY,
                    status=PlanStatus.SKIPPED,
                    snapshot=inspected.snapshot,
                    reason_code="unsafe_folder",
                    reason=str(exc),
                )
                plan_entries.append(unsafe)
                assessment_entries.append(
                    AssessmentEntry(
                        plan_entry=unsafe,
                        group=EvaluationGroup.UNSAFE,
                        age_days=None,
                        default_selected=False,
                    )
                )
                continue
            classification_time = datetime.fromtimestamp(
                latest_mtime_ns / 1_000_000_000
            ).astimezone()
            snapshot = _snapshot(metadata, tree_digest=tree_digest)
        else:
            try:
                classification_time = time_policy(metadata)
            except (OSError, OverflowError, ValueError) as exc:
                failed = PlanEntry(
                    source=source,
                    item_type=inspected.item_type,
                    status=PlanStatus.FAILED,
                    snapshot=inspected.snapshot,
                    reason_code="time_failed",
                    reason=f"cannot determine modification time: {exc}",
                )
                plan_entries.append(failed)
                assessment_entries.append(
                    AssessmentEntry(
                        plan_entry=failed,
                        group=EvaluationGroup.UNSAFE,
                        age_days=None,
                        default_selected=False,
                    )
                )
                continue
            if classification_time.tzinfo is None:
                classification_time = classification_time.astimezone()

        try:
            year = classification_time.year
            month = classification_time.month
            target_directory = (
                workspace.timeline / f"{year:04d}" / f"{year:04d}-{month:02d}"
            )
            occupied = occupied_by_directory.get(target_directory)
            if occupied is None:
                occupied = _existing_occupied_names(workspace, target_directory)
                occupied_by_directory[target_directory] = occupied
            assert inspected.item_type is not None
            target_name, renamed = available_name(
                source.name,
                inspected.item_type,
                occupied,
            )
        except WorkspaceSafetyError:
            raise
        except (OSError, OverflowError, ValueError, PlanningError) as exc:
            failed = PlanEntry(
                source=source,
                item_type=inspected.item_type,
                status=PlanStatus.FAILED,
                snapshot=snapshot,
                reason_code="planning_failed",
                reason=str(exc),
            )
            plan_entries.append(failed)
            assessment_entries.append(
                AssessmentEntry(
                    plan_entry=failed,
                    group=EvaluationGroup.UNSAFE,
                    age_days=None,
                    default_selected=False,
                )
            )
            continue

        planned = PlanEntry(
            source=source,
            item_type=inspected.item_type,
            status=PlanStatus.PLANNED,
            target_directory=target_directory,
            target=target_directory / target_name,
            classification_time=classification_time,
            year=year,
            month=month,
            snapshot=snapshot,
            renamed_from=source.name if renamed else None,
        )
        group, age_days = _evaluation_group(classification_time, reference_time)
        plan_entries.append(planned)
        assessment_entries.append(
            AssessmentEntry(
                plan_entry=planned,
                group=group,
                age_days=age_days,
                default_selected=False,
            )
        )

    plan = SortPlan(
        workspace=workspace,
        source_root=desktop,
        destination_root=workspace.timeline,
        layout=PlanLayout.MONTHLY,
        generated_at=reference_time.astimezone(UTC),
        entries=tuple(plan_entries),
    )
    return DesktopAssessment(plan=plan, entries=tuple(assessment_entries))


def build_desktop_collection_plan(
    workspace_path: str | os.PathLike[str],
    *,
    desktop_path: str | os.PathLike[str] | None = None,
    collected_at: datetime | None = None,
    time_policy: TimePolicy = modification_time_policy,
) -> SortPlan:
    """Plan one-click collection by each top-level item's modification month."""
    workspace = validate_workspace(workspace_path, require_inbox=False)
    requested_desktop = Path(desktop_path or (Path.home() / "Desktop"))
    desktop = validate_desktop_source(requested_desktop, workspace)
    reference_time = collected_at or datetime.now().astimezone()
    if reference_time.tzinfo is None:
        reference_time = reference_time.astimezone()
    try:
        children = sorted(
            (
                path
                for path in desktop.iterdir()
                if not _is_protected_desktop_application(path)
            ),
            key=lambda path: (path.name.casefold(), path.name),
        )
    except PermissionError as exc:
        raise PlanningError(f"Desktop is not readable: {desktop}") from exc
    except OSError as exc:
        raise PlanningError(f"Cannot scan Desktop: {desktop}") from exc

    occupied_by_directory: dict[Path, set[str]] = {}
    entries: list[PlanEntry] = []
    for source in children:
        metadata, inspected = _inspect_item(source)
        assert inspected is not None
        if metadata is None or inspected.status is not PlanStatus.PLANNED:
            entries.append(inspected)
            continue

        assert inspected.item_type is not None
        try:
            classification_time = time_policy(metadata)
            if classification_time.tzinfo is None:
                classification_time = classification_time.astimezone()
        except (OSError, OverflowError, ValueError) as exc:
            entries.append(
                PlanEntry(
                    source=source,
                    item_type=inspected.item_type,
                    status=PlanStatus.FAILED,
                    snapshot=inspected.snapshot,
                    reason_code="time_failed",
                    reason=f"cannot determine modification time: {exc}",
                )
            )
            continue

        if source.name.casefold().endswith(CLEANUP_PARTIAL_DOWNLOAD_SUFFIXES):
            entries.append(
                PlanEntry(
                    source=source,
                    item_type=inspected.item_type,
                    status=PlanStatus.SKIPPED,
                    classification_time=classification_time,
                    snapshot=inspected.snapshot,
                    reason_code="cleanup_partial_download",
                    reason="incomplete download residue",
                )
            )
            continue

        if inspected.item_type is ItemType.FILE:
            recommendation = cleanup_reason(source, metadata)
            if recommendation is not None:
                entries.append(
                    PlanEntry(
                        source=source,
                        item_type=ItemType.FILE,
                        status=PlanStatus.SKIPPED,
                        classification_time=classification_time,
                        snapshot=inspected.snapshot,
                        reason_code=recommendation[0],
                        reason=recommendation[1],
                    )
                )
                continue

        snapshot = inspected.snapshot
        if inspected.item_type is ItemType.DIRECTORY:
            try:
                latest_mtime_ns, tree_digest = _directory_tree_metadata(source)
            except PlanningError as exc:
                entries.append(
                    PlanEntry(
                        source=source,
                        item_type=ItemType.DIRECTORY,
                        status=PlanStatus.SKIPPED,
                        snapshot=inspected.snapshot,
                        reason_code="unsafe_folder",
                        reason=str(exc),
                    )
                )
                continue
            classification_time = datetime.fromtimestamp(
                latest_mtime_ns / 1_000_000_000
            ).astimezone()
            snapshot = _snapshot(metadata, tree_digest=tree_digest)

        year = classification_time.year
        month = classification_time.month
        target_directory = (
            workspace.timeline / f"{year:04d}" / f"{year:04d}-{month:02d}"
        )
        try:
            occupied = occupied_by_directory.get(target_directory)
            if occupied is None:
                occupied = _existing_occupied_names(workspace, target_directory)
                occupied_by_directory[target_directory] = occupied
            target_name, renamed = available_name(
                source.name,
                inspected.item_type,
                occupied,
            )
        except WorkspaceSafetyError:
            raise
        except (OSError, OverflowError, ValueError, PlanningError) as exc:
            entries.append(
                PlanEntry(
                    source=source,
                    item_type=inspected.item_type,
                    status=PlanStatus.FAILED,
                    classification_time=classification_time,
                    snapshot=snapshot,
                    reason_code="planning_failed",
                    reason=str(exc),
                )
            )
            continue
        entries.append(
            PlanEntry(
                source=source,
                item_type=inspected.item_type,
                status=PlanStatus.PLANNED,
                target_directory=target_directory,
                target=target_directory / target_name,
                classification_time=classification_time,
                year=year,
                month=month,
                snapshot=snapshot,
                renamed_from=source.name if renamed else None,
            )
        )

    return SortPlan(
        workspace=workspace,
        source_root=desktop,
        destination_root=workspace.timeline,
        layout=PlanLayout.MONTHLY,
        generated_at=reference_time.astimezone(UTC),
        entries=tuple(entries),
    )
