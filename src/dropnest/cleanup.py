"""Conservative Desktop cleanup recommendations and guarded Trash execution."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dropnest import planner
from dropnest.history import new_batch_id
from dropnest.models import (
    AssessmentEntry,
    BatchResult,
    DesktopAssessment,
    EvaluationGroup,
    ItemType,
    OperationResult,
    OperationStatus,
    PlanStatus,
)
from dropnest.workspace import (
    WorkspaceLock,
    validate_desktop_source,
    validate_workspace,
)

TrashMover = Callable[[Path], None]
BeforeEach = Callable[[AssessmentEntry], None]


def move_to_macos_trash(path: Path) -> None:
    """Ask Finder to move one path to the recoverable macOS Trash."""
    if sys.platform != "darwin":
        raise OSError("Moving items to Trash is currently supported only on macOS.")
    script = """
on run argv
    set itemPath to POSIX file (item 1 of argv)
    tell application "Finder" to delete itemPath
end run
"""
    completed = subprocess.run(
        ["/usr/bin/osascript", "-e", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if not detail:
            detail = "Finder did not accept the Trash request."
        raise OSError(f"Could not move item to macOS Trash: {detail}")


def _failure_reason(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, FileNotFoundError):
        return "source_missing", str(exc)
    if isinstance(exc, PermissionError):
        return "permission_denied", str(exc)
    if "changed after assessment" in str(exc):
        return "source_changed", str(exc)
    if "symbolic link" in str(exc) or "outside" in str(exc):
        return "safety_error", str(exc)
    return "trash_failed", str(exc)


def _validate_candidate(entry: AssessmentEntry, desktop: Path) -> None:
    planned = entry.plan_entry
    if (
        entry.group is not EvaluationGroup.CLEANUP
        or planned.status is not PlanStatus.SKIPPED
        or planned.item_type is not ItemType.FILE
        or planned.snapshot is None
        or planned.reason_code is None
        or not planned.reason_code.startswith("cleanup_")
    ):
        raise ValueError(
            f"Desktop item is not an approved cleanup recommendation: "
            f"{planned.source.name}"
        )
    if planned.source.parent != desktop:
        raise OSError(f"Cleanup source is outside the Desktop: {planned.source}")
    if planned.source.is_symlink():
        raise OSError(f"Cleanup source became a symbolic link: {planned.source}")
    try:
        metadata = planned.source.stat(follow_symlinks=False)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Cleanup source disappeared: {planned.source}"
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"Cleanup source type changed: {planned.source}")
    if planned.source.resolve(strict=True).parent != desktop.resolve():
        raise OSError(f"Cleanup source is outside the Desktop: {planned.source}")
    if not planner.snapshot_matches(planned.snapshot, metadata, planned.source):
        raise OSError(f"Cleanup source changed after assessment: {planned.source}")
    if planner.cleanup_reason(planned.source, metadata) is None:
        raise OSError(
            f"Cleanup source no longer matches a conservative rule: {planned.source}"
        )


def execute_cleanup_recommendations(
    assessment: DesktopAssessment,
    selected_names: tuple[str, ...],
    *,
    trash_mover: TrashMover = move_to_macos_trash,
    before_each: BeforeEach | None = None,
) -> BatchResult:
    """Move only explicitly selected, assessed cleanup candidates to Trash."""
    if not selected_names:
        raise ValueError("Select at least one cleanup recommendation.")
    if len(selected_names) != len(set(selected_names)):
        raise ValueError("Selected cleanup item names must be unique.")

    candidates = {
        entry.plan_entry.source.name: entry
        for entry in assessment.entries
        if entry.group is EvaluationGroup.CLEANUP
    }
    selected: list[AssessmentEntry] = []
    for name in selected_names:
        entry = candidates.get(name)
        if entry is None:
            raise ValueError(
                f"Desktop item is not in the cleanup recommendation list: {name}"
            )
        selected.append(entry)

    workspace = validate_workspace(
        assessment.plan.workspace.root,
        require_writable=True,
        require_inbox=False,
    )
    desktop = validate_desktop_source(
        assessment.plan.source_root,
        workspace,
        require_writable=True,
    )
    batch_id = new_batch_id()
    results: list[OperationResult] = []
    with WorkspaceLock(workspace):
        for entry in selected:
            if before_each is not None:
                before_each(entry)
            try:
                _validate_candidate(entry, desktop)
                trash_mover(entry.plan_entry.source)
            except (OSError, ValueError) as exc:
                code, reason = _failure_reason(exc)
                results.append(
                    OperationResult(
                        source=entry.plan_entry.source,
                        target=None,
                        status=OperationStatus.FAILED,
                        reason_code=code,
                        reason=reason,
                    )
                )
                continue
            results.append(
                OperationResult(
                    source=entry.plan_entry.source,
                    target=None,
                    status=OperationStatus.TRASHED,
                )
            )
    return BatchResult(batch_id, tuple(results))
