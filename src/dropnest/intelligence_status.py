"""Read-only Screenshot Intelligence state projection for the main app."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from dropnest.intelligence_history import (
    EVENT_RENAME,
    EVENT_UNDO,
    IntelligencePaths,
    IntelligenceStorageError,
    default_paths,
    load_config,
    read_activity,
)


@dataclass(frozen=True, slots=True)
class IntelligenceActivitySummary:
    """One credential-free activity line suitable for the native UI."""

    event_type: str
    timestamp: str
    original_name: str
    renamed_name: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class IntelligenceStatus:
    """Small UI-safe summary containing no screenshot content or credentials."""

    configured: bool
    screenshot_root: Path | None
    latest_success_time: str | None
    latest_renamed_name: str | None
    outstanding_rename_count: int
    problem: str | None
    recent_activity: tuple[IntelligenceActivitySummary, ...] = ()


def _state_path_problem(paths: IntelligencePaths) -> str | None:
    for path in (paths.root, paths.intelligence, paths.operations, paths.pending):
        if path.is_symlink():
            return f"Screenshot Intelligence state path is unsafe: {path}"
        if path.exists():
            try:
                metadata = path.stat(follow_symlinks=False)
            except OSError:
                return f"Screenshot Intelligence state path is unreadable: {path}"
            if not stat.S_ISDIR(metadata.st_mode):
                return f"Screenshot Intelligence state path is not a directory: {path}"
    return None


def get_intelligence_status(
    paths: IntelligencePaths | None = None,
) -> IntelligenceStatus:
    """Return status without creating a directory, file, lock, or history record."""
    selected = paths or default_paths()
    problem = _state_path_problem(selected)
    if problem is not None:
        return IntelligenceStatus(False, None, None, None, 0, problem)
    if not selected.config.exists():
        return IntelligenceStatus(False, None, None, None, 0, None)
    try:
        config = load_config(selected, create_state=False)
    except IntelligenceStorageError as exc:
        return IntelligenceStatus(False, None, None, None, 0, str(exc))

    screenshot_root = Path(config.screenshot_root)
    source_problem: str | None = None
    try:
        metadata = screenshot_root.stat(follow_symlinks=False)
        if screenshot_root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            source_problem = "The authorized screenshot folder is no longer safe."
        elif not os.access(screenshot_root, os.R_OK | os.W_OK | os.X_OK):
            source_problem = "The authorized screenshot folder is not accessible."
    except OSError:
        source_problem = "The authorized screenshot folder is unavailable."

    try:
        records = read_activity(selected, create_state=False)
    except IntelligenceStorageError as exc:
        return IntelligenceStatus(
            configured=True,
            screenshot_root=screenshot_root,
            latest_success_time=None,
            latest_renamed_name=None,
            outstanding_rename_count=0,
            problem=str(exc),
        )

    undone = {
        record.undo_of_event_id
        for record in records
        if record.event_type == EVENT_UNDO
    }
    renames = [record for record in records if record.event_type == EVENT_RENAME]
    outstanding = [record for record in renames if record.event_id not in undone]
    # The headline must never present an already-undone rename as active.
    # Undo activity remains visible in ``recent_activity`` below.
    latest = outstanding[-1] if outstanding else None
    recent_activity = tuple(
        IntelligenceActivitySummary(
            event_type=record.event_type,
            timestamp=record.timestamp,
            original_name=record.original_name,
            renamed_name=record.renamed_name,
            provider=record.provider,
            model=record.model,
        )
        for record in reversed(records[-5:])
    )
    return IntelligenceStatus(
        configured=True,
        screenshot_root=screenshot_root,
        latest_success_time=None if latest is None else latest.timestamp,
        latest_renamed_name=None if latest is None else latest.renamed_name,
        outstanding_rename_count=len(outstanding),
        problem=source_problem,
        recent_activity=recent_activity,
    )
