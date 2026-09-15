"""Desktop assessment and selected archive tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dropnest.history import read_history
from dropnest.models import EvaluationGroup, OperationStatus, PlanStatus
from dropnest.planner import build_desktop_assessment
from dropnest.sorter import execute_selected_plan, sort_workspace, undo_workspace
from dropnest.workspace import initialize_workspace


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def setup_desktop(tmp_path: Path):
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    return workspace, desktop


def set_age(path: Path, days: int) -> None:
    timestamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp), follow_symlinks=False)


def entries_by_name(assessment):
    return {
        entry.plan_entry.source.name: entry
        for entry in assessment.entries
    }


def test_desktop_items_follow_the_one_week_archive_mainline(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    for name, age in (
        ("today.txt", 2),
        ("waiting.txt", 14),
        ("archive.txt", 45),
    ):
        path = desktop / name
        path.write_text(name, encoding="utf-8")
        set_age(path, age)
    (desktop / "linked.txt").symlink_to(tmp_path / "outside.txt")

    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )
    entries = entries_by_name(assessment)

    assert entries["today.txt"].group is EvaluationGroup.RECENT
    assert entries["waiting.txt"].group is EvaluationGroup.ARCHIVE
    assert entries["archive.txt"].group is EvaluationGroup.ARCHIVE
    assert entries["waiting.txt"].default_selected is False
    assert entries["archive.txt"].default_selected is False
    assert entries["linked.txt"].group is EvaluationGroup.UNSAFE
    assert entries["linked.txt"].plan_entry.status is PlanStatus.SKIPPED
    assert all(not entry.default_selected for entry in entries.values())


def test_exactly_seven_complete_days_stays_on_desktop(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    boundary = desktop / "one-week.txt"
    boundary.write_text("boundary", encoding="utf-8")
    set_age(boundary, 7)

    entry = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    ).entries[0]

    assert entry.age_days == 7
    assert entry.group is EvaluationGroup.RECENT
    assert entry.default_selected is False


def test_only_direct_desktop_children_are_shown_and_folder_uses_latest_descendant(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    project = desktop / "Project"
    project.mkdir()
    nested = project / "nested.txt"
    nested.write_text("active", encoding="utf-8")
    set_age(nested, 2)
    set_age(project, 90)

    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )

    assert len(assessment.entries) == 1
    entry = assessment.entries[0]
    assert entry.plan_entry.source == project
    assert entry.group is EvaluationGroup.RECENT
    assert entry.age_days == 2
    assert entry.plan_entry.target == (
        workspace.timeline / "2026/2026-07/Project"
    )


def test_desktop_launcher_is_not_presented_as_an_archive_candidate(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    (desktop / "DropNest.app").symlink_to(tmp_path / "DropNest.app")
    (desktop / "Froganize Beta.app").mkdir()

    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )

    assert assessment.entries == ()


def test_partial_download_directory_is_left_in_place(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    partial = desktop / "unfinished.download"
    partial.mkdir()
    (partial / "payload").write_text("partial", encoding="utf-8")

    entry = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    ).entries[0]

    assert entry.group is EvaluationGroup.UNSAFE
    assert entry.plan_entry.status is PlanStatus.SKIPPED
    assert entry.plan_entry.reason_code == "cleanup_partial_download"


def test_unreadable_descendant_makes_whole_folder_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    project = desktop / "Project"
    private = project / "private"
    private.mkdir(parents=True)
    (private / "secret.txt").write_text("secret", encoding="utf-8")
    real_access = os.access

    def fake_access(path: os.PathLike[str], mode: int) -> bool:
        if Path(path) == private and mode == os.R_OK | os.X_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    entry = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    ).entries[0]

    assert entry.group is EvaluationGroup.UNSAFE
    assert entry.plan_entry.reason_code == "unsafe_folder"
    assert "not readable" in (entry.plan_entry.reason or "")


def test_selected_files_and_whole_folders_move_but_unselected_items_stay(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    selected_file = desktop / "old.txt"
    selected_file.write_text("old", encoding="utf-8")
    set_age(selected_file, 45)
    selected_folder = desktop / "Project"
    selected_folder.mkdir()
    nested = selected_folder / "nested.txt"
    nested.write_text("nested", encoding="utf-8")
    set_age(nested, 60)
    set_age(selected_folder, 60)
    unselected = desktop / "keep.txt"
    unselected.write_text("keep", encoding="utf-8")
    set_age(unselected, 80)
    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )

    result = execute_selected_plan(
        assessment.plan,
        ("old.txt", "Project"),
    )

    assert result.count(OperationStatus.MOVED) == 2
    assert not selected_file.exists()
    assert not selected_folder.exists()
    assert unselected.read_text(encoding="utf-8") == "keep"
    assert (
        workspace.timeline / "2026/2026-06/old.txt"
    ).read_text(encoding="utf-8") == "old"
    assert (
        workspace.timeline / "2026/2026-05/Project/nested.txt"
    ).read_text(encoding="utf-8") == "nested"
    records = read_history(workspace, source_roots=(desktop,))
    assert len(records) == 2
    assert {Path(record.source_path).parent for record in records} == {desktop}


def test_nested_change_after_assessment_stops_whole_folder_move(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    project = desktop / "Project"
    project.mkdir()
    nested = project / "nested.txt"
    nested.write_text("before", encoding="utf-8")
    set_age(nested, 60)
    set_age(project, 60)
    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )
    nested.write_text("changed after assessment", encoding="utf-8")

    result = execute_selected_plan(assessment.plan, ("Project",))

    assert result.results[0].status is OperationStatus.FAILED
    assert result.results[0].reason_code == "source_changed"
    assert nested.read_text(encoding="utf-8") == "changed after assessment"
    assert not any(workspace.timeline.iterdir())


def test_desktop_batch_undo_restores_original_top_level_paths(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    source = desktop / "old.txt"
    source.write_text("old", encoding="utf-8")
    set_age(source, 45)
    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )
    execute_selected_plan(assessment.plan, ("old.txt",))

    result = undo_workspace(workspace.root, source_root=desktop)

    assert result.count(OperationStatus.RESTORED) == 1
    assert source.read_text(encoding="utf-8") == "old"
    assert not (workspace.timeline / "2026/2026-06/old.txt").exists()
    assert len(read_history(workspace, source_roots=(desktop,))) == 2


def test_desktop_undo_ignores_a_newer_inbox_batch(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)

    inbox_source = workspace.inbox / "inbox-newer.txt"
    inbox_source.write_text("inbox", encoding="utf-8")
    set_age(inbox_source, 1)
    sort_workspace(workspace.root)

    desktop_source = desktop / "desktop-old.txt"
    desktop_source.write_text("desktop", encoding="utf-8")
    set_age(desktop_source, 45)
    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )
    execute_selected_plan(assessment.plan, (desktop_source.name,))

    # Simulate a valid mixed-source history whose most recently appended batch
    # belongs to the legacy Inbox flow. Desktop undo must remain source-scoped.
    lines = workspace.history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    workspace.history.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    result = undo_workspace(workspace.root, source_root=desktop)

    assert result.count(OperationStatus.RESTORED) == 1
    assert desktop_source.read_text(encoding="utf-8") == "desktop"
    assert not (workspace.timeline / "2026/2026-06/desktop-old.txt").exists()
    assert not inbox_source.exists()
    assert (workspace.timeline / "2026/2026-07/inbox-newer.txt").exists()


def test_desktop_mode_does_not_require_an_inbox_directory(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    workspace.inbox.rmdir()
    source = desktop / "old.txt"
    source.write_text("old", encoding="utf-8")
    set_age(source, 45)

    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )
    result = execute_selected_plan(assessment.plan, ("old.txt",))

    assert result.count(OperationStatus.MOVED) == 1
    assert not source.exists()
