"""Read-only workspace status inspection."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dropnest.config import load_config
from dropnest.exceptions import (
    ConfigurationError,
    DropNestError,
    HistoryError,
    WorkspaceError,
)
from dropnest.history import (
    EVENT_UNDO,
    RESULT_SUCCESS,
    latest_sort_records,
    outstanding_latest_sort_records,
    read_history,
)
from dropnest.models import PlanStatus, StatusReport
from dropnest.planner import build_desktop_assessment, build_plan
from dropnest.workspace import validate_desktop_source, validate_workspace

_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _archive_month_count(timeline: Path, problems: list[str]) -> int:
    count = 0
    try:
        years = tuple(timeline.iterdir())
    except OSError as exc:
        problems.append(f"Cannot read Timeline: {exc}")
        return 0
    for year in years:
        if year.is_symlink():
            problems.append(f"Timeline contains a symbolic-link year: {year}")
            continue
        if not year.is_dir() or not _YEAR.fullmatch(year.name):
            continue
        try:
            months = tuple(year.iterdir())
        except OSError as exc:
            problems.append(f"Cannot read archive year {year}: {exc}")
            continue
        for month in months:
            matched = _MONTH.fullmatch(month.name)
            if (
                matched
                and matched.group(1) == year.name
                and not month.is_symlink()
                and month.is_dir()
            ):
                count += 1
    return count


def inspect_status(
    workspace_path: str | os.PathLike[str],
    *,
    source_path: str | os.PathLike[str] | None = None,
    scan_source: bool = True,
) -> StatusReport:
    """Return a status report without creating or changing workspace files."""
    display_path = Path(os.path.abspath(os.fspath(workspace_path)))
    problems: list[str] = []
    try:
        workspace = validate_workspace(
            workspace_path,
            validate_configuration=False,
            require_inbox=source_path is None,
        )
    except WorkspaceError as exc:
        return StatusReport(
            workspace=display_path,
            workspace_valid=False,
            pending_count=0,
            sortable_count=0,
            skipped_count=0,
            failed_count=0,
            unreadable_count=0,
            archive_month_count=0,
            latest_batch_id=None,
            latest_sort_time=None,
            latest_moved_count=0,
            latest_undo_status="unknown",
            config_valid=False,
            history_valid=False,
            problems=(str(exc),),
        )

    config_valid = True
    try:
        load_config(workspace.config)
    except ConfigurationError as exc:
        config_valid = False
        problems.append(str(exc))

    history_source_roots: tuple[Path, ...] = ()
    desktop: Path | None = None
    if source_path is not None:
        try:
            desktop = validate_desktop_source(source_path, workspace)
        except WorkspaceError as exc:
            problems.append(str(exc))
        else:
            history_source_roots = (desktop,)

    pending = sortable = skipped = failed = unreadable = 0
    if config_valid and scan_source:
        try:
            if desktop is None:
                plan = build_plan(workspace.root)
            else:
                plan = build_desktop_assessment(
                    workspace.root,
                    desktop_path=desktop,
                ).plan
        except DropNestError as exc:
            problems.append(str(exc))
        else:
            pending = len(plan.entries)
            sortable = plan.count(PlanStatus.PLANNED)
            skipped = plan.count(PlanStatus.SKIPPED)
            failed = plan.count(PlanStatus.FAILED)
            unreadable = sum(
                entry.reason_code == "unreadable" for entry in plan.entries
            )

    history_valid = True
    records = ()
    try:
        records = read_history(
            workspace,
            source_roots=history_source_roots,
        )
    except HistoryError as exc:
        history_valid = False
        problems.append(str(exc))

    active_source_root = desktop if desktop is not None else workspace.inbox
    latest = latest_sort_records(records, source_root=active_source_root)
    latest_batch_id = latest[0].batch_id if latest else None
    latest_sort_time = latest[-1].timestamp if latest else None
    latest_moved_count = len(latest)
    if not latest:
        latest_undo_status = "none"
    else:
        latest_ids = {record.event_id for record in latest}
        related_undo = [
            record
            for record in records
            if record.event_type == EVENT_UNDO
            and record.undo_of_event_id in latest_ids
        ]
        outstanding = outstanding_latest_sort_records(
            records,
            source_root=active_source_root,
        )
        if not related_undo:
            latest_undo_status = "not_started"
        elif not outstanding:
            latest_undo_status = "complete"
        elif any(record.result == RESULT_SUCCESS for record in related_undo):
            latest_undo_status = "partial"
        else:
            latest_undo_status = "failed"

    archive_month_count = _archive_month_count(workspace.timeline, problems)
    return StatusReport(
        workspace=workspace.root,
        workspace_valid=config_valid and history_valid and not problems,
        pending_count=pending,
        sortable_count=sortable,
        skipped_count=skipped,
        failed_count=failed,
        unreadable_count=unreadable,
        archive_month_count=archive_month_count,
        latest_batch_id=latest_batch_id,
        latest_sort_time=latest_sort_time,
        latest_moved_count=latest_moved_count,
        latest_undo_status=latest_undo_status,
        config_valid=config_valid,
        history_valid=history_valid,
        problems=tuple(problems),
    )
