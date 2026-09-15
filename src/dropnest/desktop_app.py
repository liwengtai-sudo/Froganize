"""Application services for the native Froganize Desktop interface.

This module deliberately contains no GUI, HTTP, or browser code.  It fixes the
workspace and Desktop scope once, then delegates all planning and filesystem
mutations to the existing DropNest core services.
"""

from __future__ import annotations

import hmac
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from dropnest.cleanup import (
    TrashMover,
    execute_cleanup_recommendations,
    move_to_macos_trash,
)
from dropnest.history import project_history_calendar, read_history
from dropnest.models import (
    BatchResult,
    DesktopAssessment,
    HistoryCalendar,
    StatusReport,
)
from dropnest.planner import build_desktop_assessment
from dropnest.sorter import collect_desktop, execute_selected_plan, undo_workspace
from dropnest.status import inspect_status
from dropnest.workspace import validate_desktop_source, validate_workspace

PathOpener = Callable[[Path], None]

_EXPIRED_ASSESSMENT = (
    "This Desktop assessment has expired. Assess the Desktop again."
)


def _default_folder_opener(path: Path) -> None:
    """Open a fixed application folder with the native macOS Finder."""
    if sys.platform != "darwin":
        raise OSError("Opening folders is currently supported only on macOS.")
    subprocess.run(["open", str(path)], check=True)


def _default_item_revealer(path: Path) -> None:
    """Reveal one assessed top-level item with the native macOS Finder."""
    if sys.platform != "darwin":
        raise OSError("Revealing files is currently supported only on macOS.")
    subprocess.run(["open", "-R", str(path)], check=True)


def _selected_names(
    values: Iterable[str],
    *,
    action_label: str,
) -> tuple[str, ...]:
    """Freeze and minimally validate names before claiming an assessment."""
    if isinstance(values, (str, bytes)):
        raise ValueError("Selected Desktop item names must be a collection.")
    names = tuple(values)
    if not names:
        raise ValueError(f"Select at least one Desktop item to {action_label}.")
    if len(names) > 10_000:
        raise ValueError("Too many Desktop items were selected.")
    for name in names:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\0" in name
        ):
            raise ValueError("Selected Desktop item names are invalid.")
    if len(names) != len(set(names)):
        raise ValueError("Selected Desktop item names must be unique.")
    return names


@dataclass(frozen=True, slots=True)
class AssessmentSession:
    """One short-lived Desktop snapshot exposed to the presentation layer."""

    id: str
    assessment: DesktopAssessment


class DesktopApplication:
    """Validated application boundary used by a native Desktop window.

    Exactly one assessment is current at a time.  Mutating actions claim and
    clear it before delegating to the core, so an old or double-clicked UI
    action cannot execute the same snapshot twice.
    """

    def __init__(
        self,
        workspace_path: str | Path,
        *,
        desktop_path: str | Path | None = None,
        opener: PathOpener = _default_folder_opener,
        revealer: PathOpener = _default_item_revealer,
        trasher: TrashMover = move_to_macos_trash,
    ) -> None:
        workspace = validate_workspace(workspace_path, require_inbox=False)
        requested_desktop = (
            Path.home() / "Desktop" if desktop_path is None else desktop_path
        )
        desktop = validate_desktop_source(requested_desktop, workspace)

        self._workspace = workspace.root
        self._desktop = desktop
        self._opener = opener
        self._revealer = revealer
        self._trasher = trasher
        self._assessment_id: str | None = None
        self._assessment: DesktopAssessment | None = None
        self._assessment_lock = threading.Lock()

    @classmethod
    def create(
        cls,
        workspace_path: str | Path,
        *,
        desktop_path: str | Path | None = None,
        opener: PathOpener = _default_folder_opener,
        revealer: PathOpener = _default_item_revealer,
        trasher: TrashMover = move_to_macos_trash,
    ) -> DesktopApplication:
        """Create an application with one validated, immutable path scope."""
        return cls(
            workspace_path,
            desktop_path=desktop_path,
            opener=opener,
            revealer=revealer,
            trasher=trasher,
        )

    @property
    def workspace(self) -> Path:
        """Resolved workspace root fixed when this service was created."""
        return self._workspace

    @property
    def desktop(self) -> Path:
        """Resolved Desktop source fixed when this service was created."""
        return self._desktop

    @property
    def timeline(self) -> Path:
        """Fixed Timeline path derived from the validated workspace."""
        return self._workspace / "Timeline"

    def assess(self) -> AssessmentSession:
        """Build and retain one new read-only Desktop assessment."""
        assessment = build_desktop_assessment(
            self._workspace,
            desktop_path=self._desktop,
        )
        assessment_id = secrets.token_urlsafe(24)
        with self._assessment_lock:
            self._assessment_id = assessment_id
            self._assessment = assessment
        return AssessmentSession(assessment_id, assessment)

    def status(self, *, scan_source: bool = False) -> StatusReport:
        """Inspect only this application's fixed workspace and Desktop."""
        return inspect_status(
            self._workspace,
            source_path=self._desktop,
            scan_source=scan_source,
        )

    def archive(
        self,
        assessment_id: str,
        selected_names: Iterable[str],
    ) -> BatchResult:
        """Claim an assessment and archive only its explicitly selected items."""
        names = _selected_names(selected_names, action_label="archive")
        assessment = self._claim_assessment(assessment_id)
        return execute_selected_plan(assessment.plan, names)

    def trash(
        self,
        assessment_id: str,
        selected_names: Iterable[str],
    ) -> BatchResult:
        """Claim an assessment and Trash only approved cleanup candidates."""
        names = _selected_names(selected_names, action_label="move to Trash")
        assessment = self._claim_assessment(assessment_id)
        return execute_cleanup_recommendations(
            assessment,
            names,
            trash_mover=self._trasher,
        )

    def collect_all(self) -> BatchResult:
        """Collect safe Desktop children by modification month in one undo batch."""
        self.clear_assessment()
        _plan, result = collect_desktop(
            self._workspace,
            desktop_path=self._desktop,
        )
        return result

    def undo(self, *, expected_batch_id: str | None = None) -> BatchResult:
        """Discard any current assessment and undo the latest Desktop batch."""
        self.clear_assessment()
        return undo_workspace(
            self._workspace,
            source_root=self._desktop,
            expected_batch_id=expected_batch_id,
        )

    def history_calendar(self) -> HistoryCalendar:
        """Return validated Desktop organization history without changing files."""
        workspace = validate_workspace(self._workspace, require_inbox=False)
        desktop = validate_desktop_source(self._desktop, workspace)
        records = read_history(workspace, source_roots=(desktop,))
        return project_history_calendar(records, source_root=desktop)

    def open_folder(self, target_name: str) -> Path:
        """Open only the fixed Desktop or Timeline folder."""
        workspace = validate_workspace(self._workspace, require_inbox=False)
        if target_name == "desktop":
            target = validate_desktop_source(self._desktop, workspace)
        elif target_name == "timeline":
            target = workspace.timeline
        else:
            raise ValueError("Open target must be 'desktop' or 'timeline'.")
        self._opener(target)
        return target

    def reveal_item(self, assessment_id: str, name: str) -> Path:
        """Reveal an existing direct child from the current assessment only."""
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\0" in name
        ):
            raise ValueError("Desktop item name is invalid.")
        assessment = self._get_assessment(assessment_id)
        matching = [
            entry.plan_entry.source
            for entry in assessment.entries
            if entry.plan_entry.source.name == name
        ]
        if not matching:
            raise ValueError("Desktop item is not in the current assessment.")
        target = matching[0]
        if target.parent != self._desktop:
            raise ValueError("Desktop item is not a direct child of the Desktop.")

        workspace = validate_workspace(self._workspace, require_inbox=False)
        desktop = validate_desktop_source(self._desktop, workspace)
        if target.parent != desktop or not target.exists():
            raise ValueError("Desktop item no longer exists.")
        self._revealer(target)
        return target

    def clear_assessment(self) -> None:
        """Invalidate the current assessment without changing any files."""
        with self._assessment_lock:
            self._assessment_id = None
            self._assessment = None

    def _get_assessment(self, assessment_id: str) -> DesktopAssessment:
        with self._assessment_lock:
            if not self._assessment_matches(assessment_id):
                raise ValueError(_EXPIRED_ASSESSMENT)
            assert self._assessment is not None
            return self._assessment

    def _claim_assessment(self, assessment_id: str) -> DesktopAssessment:
        with self._assessment_lock:
            if not self._assessment_matches(assessment_id):
                raise ValueError(_EXPIRED_ASSESSMENT)
            assert self._assessment is not None
            assessment = self._assessment
            self._assessment_id = None
            self._assessment = None
            return assessment

    def _assessment_matches(self, assessment_id: str) -> bool:
        return (
            isinstance(assessment_id, str)
            and bool(assessment_id)
            and self._assessment_id is not None
            and self._assessment is not None
            and hmac.compare_digest(assessment_id, self._assessment_id)
        )
