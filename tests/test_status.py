"""Read-only workspace status tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from dropnest.sorter import sort_workspace, undo_workspace
from dropnest.status import inspect_status
from dropnest.workspace import initialize_workspace


def snapshot_tree(root: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        snapshot[relative] = path.read_bytes() if path.is_file() else None
    return snapshot


def test_status_counts_items_and_archive_months_without_changes(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    (workspace.inbox / "report.pdf").touch()
    (workspace.inbox / ".hidden").touch()
    (workspace.timeline / "2025/2025-12").mkdir(parents=True)
    (workspace.timeline / "2026/2026-01").mkdir(parents=True)
    (workspace.timeline / "misc/not-a-month").mkdir(parents=True)
    before = snapshot_tree(workspace.root)

    report = inspect_status(workspace.root)

    after = snapshot_tree(workspace.root)
    assert report.workspace_valid
    assert report.pending_count == 2
    assert report.sortable_count == 1
    assert report.skipped_count == 1
    assert report.archive_month_count == 2
    assert before == after


def test_status_reports_latest_sort_and_undo(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    source = workspace.inbox / "report.pdf"
    source.touch()
    moment = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    os.utime(source, (moment, moment))
    _, batch = sort_workspace(workspace.root)

    sorted_report = inspect_status(workspace.root)
    undo_workspace(workspace.root)
    undone_report = inspect_status(workspace.root)

    assert sorted_report.latest_batch_id == batch.batch_id
    assert sorted_report.latest_moved_count == 1
    assert sorted_report.latest_undo_status == "not_started"
    assert undone_report.latest_undo_status == "complete"


def test_status_reports_unreadable_item_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    source = workspace.inbox / "private.txt"
    source.touch()
    real_access = os.access

    def fake_access(path, mode):
        if Path(path) == source and mode == os.R_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    report = inspect_status(workspace.root)

    assert report.pending_count == 1
    assert report.skipped_count == 1
    assert report.unreadable_count == 1


def test_status_reports_damaged_config_and_history_without_writing(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    workspace.config.write_text("{bad", encoding="utf-8")
    workspace.history.write_text("{bad\n", encoding="utf-8")
    before = snapshot_tree(workspace.root)

    report = inspect_status(workspace.root)

    assert not report.workspace_valid
    assert not report.config_valid
    assert not report.history_valid
    assert len(report.problems) == 2
    assert snapshot_tree(workspace.root) == before


def test_status_reports_nonexistent_workspace(tmp_path: Path) -> None:
    report = inspect_status(tmp_path / "missing")

    assert not report.workspace_valid
    assert report.problems
