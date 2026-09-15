"""History validation and latest-batch undo tests."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dropnest.sorter as sorter_module
from dropnest.exceptions import HistoryError
from dropnest.history import project_history_calendar, read_history
from dropnest.models import OperationStatus
from dropnest.sorter import sort_workspace, undo_workspace
from dropnest.workspace import initialize_workspace


def sorted_workspace(tmp_path: Path, names: tuple[str, ...] = ("a.txt",)):
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    moment = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    for name in names:
        path = workspace.inbox / name
        path.write_text(name, encoding="utf-8")
        os.utime(path, (moment, moment))
    _, result = sort_workspace(workspace.root)
    return workspace, result


def test_history_is_append_only_json_lines(tmp_path: Path) -> None:
    workspace, result = sorted_workspace(tmp_path, ("a.txt", "b.txt"))

    lines = workspace.history.read_text(encoding="utf-8").splitlines()
    records = read_history(workspace)

    assert len(lines) == 2
    assert len(records) == 2
    assert {record.batch_id for record in records} == {result.batch_id}
    assert all(json.loads(line)["schema_version"] == 1 for line in lines)


def test_damaged_and_incomplete_history_are_rejected(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    workspace.history.write_text('{"schema_version":1}\n', encoding="utf-8")

    with pytest.raises(HistoryError, match="missing fields"):
        read_history(workspace)

    workspace.history.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(HistoryError, match="damaged"):
        read_history(workspace)


def test_history_path_traversal_is_rejected(tmp_path: Path) -> None:
    workspace, _ = sorted_workspace(tmp_path)
    raw = json.loads(workspace.history.read_text(encoding="utf-8"))
    raw["source_path"] = str(workspace.inbox / ".." / ".." / "outside.txt")
    workspace.history.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    with pytest.raises(HistoryError, match="path traversal"):
        read_history(workspace)


def test_undo_restores_latest_batch_to_original_paths(tmp_path: Path) -> None:
    workspace, _ = sorted_workspace(tmp_path, ("a.txt", "b.txt"))

    result = undo_workspace(workspace.root)

    assert result.count(OperationStatus.RESTORED) == 2
    assert (workspace.inbox / "a.txt").read_text(encoding="utf-8") == "a.txt"
    assert (workspace.inbox / "b.txt").read_text(encoding="utf-8") == "b.txt"
    assert not (workspace.timeline / "2026/2026-07/a.txt").exists()
    assert len(read_history(workspace)) == 4


def test_repeated_undo_does_not_restore_twice_or_cross_to_older_batch(
    tmp_path: Path,
) -> None:
    workspace, _ = sorted_workspace(tmp_path, ("old.txt",))
    (workspace.inbox / "new.txt").write_text("new", encoding="utf-8")
    moment = datetime(2026, 8, 1, tzinfo=UTC).timestamp()
    os.utime(workspace.inbox / "new.txt", (moment, moment))
    sort_workspace(workspace.root)
    first_undo = undo_workspace(workspace.root)

    repeated = undo_workspace(workspace.root)

    assert first_undo.count(OperationStatus.RESTORED) == 1
    assert repeated.batch_id is None
    assert repeated.results == ()
    assert (workspace.inbox / "new.txt").exists()
    assert (workspace.timeline / "2026/2026-07/old.txt").exists()


def test_history_calendar_groups_batches_and_only_latest_is_undoable(
    tmp_path: Path,
) -> None:
    workspace, first = sorted_workspace(tmp_path, ("old.txt",))
    (workspace.inbox / "new.txt").write_text("new", encoding="utf-8")
    moment = datetime(2026, 8, 1, tzinfo=UTC).timestamp()
    os.utime(workspace.inbox / "new.txt", (moment, moment))
    _, second = sort_workspace(workspace.root)
    records = read_history(workspace)
    dated = tuple(
        replace(
            record,
            timestamp=(
                "2026-07-10T08:00:00Z"
                if record.batch_id == first.batch_id
                else "2026-08-12T09:30:00Z"
            ),
        )
        for record in records
    )

    calendar = project_history_calendar(dated, source_root=workspace.inbox)

    assert [batch.batch_id for batch in calendar.batches] == [
        second.batch_id,
        first.batch_id,
    ]
    assert calendar.latest_undoable_batch_id == second.batch_id
    assert calendar.batches[0].undoable is True
    assert calendar.batches[1].undoable is False
    assert calendar.batches[0].items[0].source.name == "new.txt"


def test_history_calendar_marks_successful_and_failed_restore_attempts(
    tmp_path: Path,
) -> None:
    workspace, _result = sorted_workspace(tmp_path, ("a.txt", "b.txt"))
    (workspace.inbox / "a.txt").write_text("occupied", encoding="utf-8")

    undo_workspace(workspace.root)
    calendar = project_history_calendar(
        read_history(workspace), source_root=workspace.inbox
    )

    items = {item.source.name: item for item in calendar.batches[0].items}
    assert items["a.txt"].restored is False
    assert items["a.txt"].restore_failed is True
    assert items["b.txt"].restored is True
    assert items["b.txt"].restore_failed is False
    assert calendar.batches[0].undoable is True


def test_calendar_undo_rejects_a_stale_expected_batch_without_moving_files(
    tmp_path: Path,
) -> None:
    workspace, first = sorted_workspace(tmp_path, ("old.txt",))
    (workspace.inbox / "new.txt").write_text("new", encoding="utf-8")
    moment = datetime(2026, 8, 1, tzinfo=UTC).timestamp()
    os.utime(workspace.inbox / "new.txt", (moment, moment))
    sort_workspace(workspace.root)
    latest_target = workspace.timeline / "2026/2026-08/new.txt"

    with pytest.raises(HistoryError, match="history changed"):
        undo_workspace(workspace.root, expected_batch_id=first.batch_id)

    assert latest_target.read_text(encoding="utf-8") == "new"
    assert not (workspace.inbox / "new.txt").exists()


def test_original_path_conflict_fails_without_overwrite_and_can_retry(
    tmp_path: Path,
) -> None:
    workspace, _ = sorted_workspace(tmp_path)
    original = workspace.inbox / "a.txt"
    original.write_text("new occupant", encoding="utf-8")

    first = undo_workspace(workspace.root)

    assert first.results[0].reason_code == "original_conflict"
    assert original.read_text(encoding="utf-8") == "new occupant"
    original.unlink()

    second = undo_workspace(workspace.root)

    assert second.count(OperationStatus.RESTORED) == 1
    assert original.read_text(encoding="utf-8") == "a.txt"


def test_missing_archived_target_is_reported_and_other_item_restores(
    tmp_path: Path,
) -> None:
    workspace, _ = sorted_workspace(tmp_path, ("a.txt", "b.txt"))
    (workspace.timeline / "2026/2026-07/a.txt").unlink()

    result = undo_workspace(workspace.root)

    assert result.count(OperationStatus.FAILED) == 1
    assert result.count(OperationStatus.RESTORED) == 1
    assert {item.reason_code for item in result.results} >= {"target_missing", None}
    assert (workspace.inbox / "b.txt").exists()


def test_undo_rejects_archived_item_type_change(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    source = workspace.inbox / "Project"
    source.mkdir()
    moment = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    os.utime(source, (moment, moment))
    sort_workspace(workspace.root)
    archived = workspace.timeline / "2026/2026-07/Project"
    archived.rmdir()
    archived.write_text("replacement file", encoding="utf-8")

    result = undo_workspace(workspace.root)

    assert result.results[0].reason_code == "type_changed"
    assert archived.read_text(encoding="utf-8") == "replacement file"
    assert not source.exists()


def test_undo_history_write_failure_rolls_back_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _ = sorted_workspace(tmp_path)
    original = workspace.inbox / "a.txt"
    archived = workspace.timeline / "2026/2026-07/a.txt"
    history_before = workspace.history.read_bytes()

    def fail_history(*_args, **_kwargs) -> None:
        raise HistoryError("simulated undo history failure")

    monkeypatch.setattr(sorter_module, "append_history", fail_history)

    with pytest.raises(HistoryError, match="simulated undo history failure"):
        undo_workspace(workspace.root)

    assert not original.exists()
    assert archived.read_text(encoding="utf-8") == "a.txt"
    assert workspace.history.read_bytes() == history_before
    assert not workspace.lock.exists()


def test_undo_reports_history_and_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _ = sorted_workspace(tmp_path)
    original = workspace.inbox / "a.txt"
    archived = workspace.timeline / "2026/2026-07/a.txt"
    history_before = workspace.history.read_bytes()
    real_rename = sorter_module._rename_no_replace
    rename_calls = 0

    def fail_history(*_args, **_kwargs) -> None:
        raise HistoryError("simulated undo history failure")

    def fail_rollback(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated undo rollback failure")
        real_rename(source, destination)

    monkeypatch.setattr(sorter_module, "append_history", fail_history)
    monkeypatch.setattr(sorter_module, "_rename_no_replace", fail_rollback)

    with pytest.raises(
        HistoryError,
        match="Undo history write failed.*automatic rollback also failed",
    ):
        undo_workspace(workspace.root)

    assert original.read_text(encoding="utf-8") == "a.txt"
    assert not archived.exists()
    assert workspace.history.read_bytes() == history_before
    assert not workspace.lock.exists()
