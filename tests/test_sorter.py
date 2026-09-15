"""Checked sort execution tests."""

from __future__ import annotations

import errno
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dropnest.sorter as sorter_module
from dropnest.exceptions import HistoryError
from dropnest.history import read_history
from dropnest.models import OperationStatus
from dropnest.planner import build_desktop_collection_plan, build_plan
from dropnest.sorter import collect_desktop, execute_plan, sort_workspace, undo_workspace
from dropnest.workspace import initialize_workspace


def setup_file(tmp_path: Path, name: str = "report.pdf") -> tuple[Path, Path]:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    source = workspace.inbox / name
    source.write_text("content", encoding="utf-8")
    timestamp = datetime(2026, 7, 19, 10, 30, tzinfo=UTC).timestamp()
    os.utime(source, (timestamp, timestamp))
    return workspace.root, source


def test_execute_moves_file_and_records_history(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)

    result = execute_plan(plan)

    target = root / "Timeline/2026/2026-07/report.pdf"
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "content"
    assert result.count(OperationStatus.MOVED) == 1
    records = read_history(plan.workspace)
    assert len(records) == 1
    assert records[0].source_path == str(source)
    assert records[0].destination_path == str(target)
    assert records[0].result == "success"
    assert "content" not in workspace_history_text(plan.workspace.history)


def workspace_history_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_folder_moves_as_one_intact_tree(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    source = workspace.inbox / "Project"
    source.mkdir()
    nested = source / "src" / "main.py"
    nested.parent.mkdir()
    nested.write_text("print('safe')", encoding="utf-8")
    moment = datetime(2025, 12, 1, tzinfo=UTC).timestamp()
    os.utime(source, (moment, moment))

    result = execute_plan(build_plan(workspace.root))

    target = workspace.timeline / "2025/2025-12/Project"
    assert result.count(OperationStatus.MOVED) == 1
    assert (target / "src/main.py").read_text(encoding="utf-8") == "print('safe')"
    assert not source.exists()


def test_changed_source_fails_without_moving(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    source.write_text("changed and longer", encoding="utf-8")

    result = execute_plan(plan)

    assert result.results[0].status is OperationStatus.FAILED
    assert result.results[0].reason_code == "source_changed"
    assert source.exists()
    assert list((root / "Timeline").iterdir()) == []


def test_disappeared_source_fails_and_other_item_continues(tmp_path: Path) -> None:
    root, first = setup_file(tmp_path, "a.txt")
    second = root / "Inbox" / "b.txt"
    second.write_text("b", encoding="utf-8")
    timestamp = datetime(2026, 7, 19, tzinfo=UTC).timestamp()
    os.utime(second, (timestamp, timestamp))
    plan = build_plan(root)
    first.unlink()

    result = execute_plan(plan)

    assert result.count(OperationStatus.FAILED) == 1
    assert result.count(OperationStatus.MOVED) == 1
    assert (root / "Timeline/2026/2026-07/b.txt").exists()


def test_target_occupied_after_plan_is_not_overwritten(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    target = plan.entries[0].target
    assert target is not None

    def occupy(_entry) -> None:
        target.parent.mkdir(parents=True)
        target.write_text("existing", encoding="utf-8")

    result = execute_plan(plan, before_each=occupy)

    assert result.results[0].reason_code == "target_conflict"
    assert source.read_text(encoding="utf-8") == "content"
    assert target.read_text(encoding="utf-8") == "existing"


def test_case_variant_occupied_after_plan_is_not_overwritten(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    target = plan.entries[0].target
    assert target is not None

    def occupy(_entry) -> None:
        target.parent.mkdir(parents=True)
        (target.parent / "REPORT.PDF").write_text("existing", encoding="utf-8")

    result = execute_plan(plan, before_each=occupy)

    assert result.results[0].reason_code == "target_conflict"
    assert source.exists()


def test_sort_replans_current_state_using_shared_planner(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    preview = build_plan(root)
    preview_target = preview.entries[0].target
    assert preview_target is not None
    preview_target.parent.mkdir(parents=True)
    preview_target.write_text("arrived later", encoding="utf-8")

    fresh_plan, result = sort_workspace(root)

    assert fresh_plan.entries[0].target is not None
    assert fresh_plan.entries[0].target.name == "report (1).pdf"
    assert result.count(OperationStatus.MOVED) == 1
    assert preview_target.read_text(encoding="utf-8") == "arrived later"
    assert not source.exists()


def test_damaged_history_stops_execution_before_move(tmp_path: Path) -> None:
    root, source = setup_file(tmp_path)
    workspace = build_plan(root).workspace
    workspace.history.write_text("{bad\n", encoding="utf-8")

    with pytest.raises(HistoryError, match="damaged"):
        execute_plan(build_plan(root))

    assert source.exists()
    assert list(workspace.timeline.iterdir()) == []


def test_history_write_failure_is_reported_and_move_is_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)

    def fail_history(*_args, **_kwargs) -> None:
        raise HistoryError("simulated history failure")

    monkeypatch.setattr("dropnest.sorter.append_history", fail_history)

    with pytest.raises(HistoryError, match="simulated"):
        execute_plan(plan)

    assert source.read_text(encoding="utf-8") == "content"
    assert not (root / "Timeline/2026/2026-07/report.pdf").exists()


@pytest.mark.parametrize(
    ("error_number", "expected_reason"),
    (
        (errno.ENOSPC, "insufficient_space"),
        (errno.EBUSY, "source_busy"),
        (errno.ETXTBSY, "source_busy"),
    ),
)
def test_move_os_errors_are_classified_without_losing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
    expected_reason: str,
) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    target = plan.entries[0].target
    assert target is not None

    def fail_move(_source: Path, destination: Path) -> None:
        raise OSError(error_number, os.strerror(error_number), destination)

    monkeypatch.setattr(sorter_module, "_rename_no_replace", fail_move)

    result = execute_plan(plan)

    assert result.results[0].status is OperationStatus.FAILED
    assert result.results[0].reason_code == expected_reason
    assert source.read_text(encoding="utf-8") == "content"
    assert not target.exists()
    assert read_history(plan.workspace) == ()


def test_source_permission_change_after_planning_fails_without_moving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    target = plan.entries[0].target
    assert target is not None
    real_access = os.access

    def fake_access(path: os.PathLike[str], mode: int) -> bool:
        if Path(path) == source and mode == os.R_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(sorter_module.os, "access", fake_access)

    result = execute_plan(plan)

    assert result.results[0].status is OperationStatus.FAILED
    assert result.results[0].reason_code == "permission_denied"
    assert source.read_text(encoding="utf-8") == "content"
    assert not target.exists()
    assert read_history(plan.workspace) == ()


def test_history_write_and_rollback_failure_reports_both_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    target = plan.entries[0].target
    assert target is not None
    history_before = plan.workspace.history.read_bytes()
    real_rename = sorter_module._rename_no_replace
    rename_calls = 0

    def fail_history(*_args, **_kwargs) -> None:
        raise HistoryError("simulated sort history failure")

    def fail_rollback(move_source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated sort rollback failure")
        real_rename(move_source, destination)

    monkeypatch.setattr(sorter_module, "append_history", fail_history)
    monkeypatch.setattr(sorter_module, "_rename_no_replace", fail_rollback)

    with pytest.raises(
        HistoryError,
        match="History write failed.*automatic rollback also failed",
    ):
        execute_plan(plan)

    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "content"
    assert plan.workspace.history.read_bytes() == history_before


def test_executor_rejects_target_that_does_not_match_planned_directory(
    tmp_path: Path,
) -> None:
    root, source = setup_file(tmp_path)
    plan = build_plan(root)
    unsafe_entry = replace(plan.entries[0], target=plan.workspace.inbox / "bad.pdf")
    unsafe_plan = replace(plan, entries=(unsafe_entry,))

    result = execute_plan(unsafe_plan)

    assert result.results[0].reason_code == "safety_error"
    assert source.exists()
    assert not (plan.workspace.inbox / "bad.pdf").exists()


def test_collect_desktop_moves_by_modification_month_in_one_undo_batch(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    report = desktop / "report.pdf"
    report.write_text("report", encoding="utf-8")
    project = desktop / "Project"
    project.mkdir()
    nested = project / "nested.txt"
    nested.write_text("nested", encoding="utf-8")
    report_time = datetime(2025, 12, 15, 12, 0, tzinfo=UTC)
    project_time = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    os.utime(report, (report_time.timestamp(), report_time.timestamp()))
    os.utime(nested, (project_time.timestamp(), project_time.timestamp()))
    old_project_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).timestamp()
    os.utime(project, (old_project_time, old_project_time))
    (desktop / ".hidden").write_text("hidden", encoding="utf-8")
    (desktop / "Froganize.app").mkdir()
    collected_at = datetime(2026, 9, 1, 15, 30, tzinfo=UTC)

    plan, result = collect_desktop(
        workspace.root,
        desktop_path=desktop,
        collected_at=collected_at,
    )

    report_target = workspace.timeline / "2025/2025-12/report.pdf"
    project_target = workspace.timeline / "2026/2026-07/Project"
    assert result.count(OperationStatus.MOVED) == 2
    assert report_target.read_text(encoding="utf-8") == "report"
    assert (project_target / "nested.txt").read_text(encoding="utf-8") == "nested"
    assert (desktop / ".hidden").exists()
    assert (desktop / "Froganize.app").exists()
    records = read_history(plan.workspace, source_roots=(desktop.resolve(),))
    assert {record.batch_id for record in records} == {result.batch_id}
    assert {record.classification_time for record in records} == {
        datetime.fromtimestamp(report_time.timestamp()).astimezone().isoformat(),
        datetime.fromtimestamp(project_time.timestamp()).astimezone().isoformat(),
    }

    undone = undo_workspace(workspace.root, source_root=desktop)

    assert undone.count(OperationStatus.RESTORED) == 2
    assert report.read_text(encoding="utf-8") == "report"
    assert (project / "nested.txt").read_text(encoding="utf-8") == "nested"
    assert not report_target.exists()
    assert not project_target.exists()


def test_collection_target_occupied_after_planning_does_not_overwrite_others(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    first = desktop / "a.txt"
    second = desktop / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    moment = datetime(2026, 9, 1, 12, 0, tzinfo=UTC).timestamp()
    os.utime(first, (moment, moment))
    os.utime(second, (moment, moment))
    plan = build_desktop_collection_plan(
        workspace.root,
        desktop_path=desktop,
        collected_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
    )
    month = workspace.timeline / "2026/2026-09"
    month.mkdir(parents=True)
    (month / "a.txt").write_text("external", encoding="utf-8")

    result = execute_plan(plan, source_root=desktop)

    assert first.read_text(encoding="utf-8") == "a"
    assert not second.exists()
    assert (month / "a.txt").read_text(encoding="utf-8") == "external"
    assert (month / "b.txt").read_text(encoding="utf-8") == "b"
    assert result.count(OperationStatus.FAILED) == 1
    assert result.count(OperationStatus.MOVED) == 1
    records = read_history(plan.workspace, source_roots=(desktop.resolve(),))
    assert len(records) == 1
    assert records[0].source_path == str(second)


def test_empty_desktop_collection_does_not_create_month_directories(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / ".DS_Store").touch()

    _plan, result = collect_desktop(
        workspace.root,
        desktop_path=desktop,
        collected_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
    )

    assert result.count(OperationStatus.MOVED) == 0
    assert list(workspace.timeline.iterdir()) == []


def test_collection_rejects_a_tampered_destination_root_before_moving(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    source = desktop / "report.pdf"
    source.write_text("important", encoding="utf-8")
    plan = build_desktop_collection_plan(
        workspace.root,
        desktop_path=desktop,
        collected_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    tampered = replace(plan, destination_root=outside)

    with pytest.raises(
        sorter_module.WorkspaceSafetyError,
        match="destination root",
    ):
        execute_plan(tampered, source_root=desktop)

    assert source.read_text(encoding="utf-8") == "important"
    assert list(outside.iterdir()) == []
    assert read_history(plan.workspace, source_roots=(desktop.resolve(),)) == ()
