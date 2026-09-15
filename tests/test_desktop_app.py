"""Framework-free native Desktop application service tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dropnest.desktop_app import DesktopApplication
from dropnest.exceptions import WorkspaceError
from dropnest.models import EvaluationGroup, OperationStatus
from dropnest.workspace import initialize_workspace


def application_setup(
    tmp_path: Path,
    *,
    opened: list[Path] | None = None,
    revealed: list[Path] | None = None,
    trasher=None,
) -> tuple[DesktopApplication, Path, Path]:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    def reject_real_trash(path: Path) -> None:
        raise AssertionError(f"A test attempted to use the real Trash: {path}")

    application = DesktopApplication.create(
        workspace.root,
        desktop_path=desktop,
        opener=(opened if opened is not None else []).append,
        revealer=(revealed if revealed is not None else []).append,
        trasher=trasher or reject_real_trash,
    )
    return application, workspace.root, desktop


def old_file(desktop: Path, name: str = "report.pdf") -> Path:
    source = desktop / name
    source.write_text("desktop application test", encoding="utf-8")
    timestamp = datetime(2020, 7, 24, 12, 0, tzinfo=UTC).timestamp()
    os.utime(source, (timestamp, timestamp))
    return source


def test_create_fixes_validated_read_only_paths(tmp_path: Path) -> None:
    application, workspace, desktop = application_setup(tmp_path)

    assert application.workspace == workspace.resolve()
    assert application.desktop == desktop.resolve()
    assert application.timeline == workspace.resolve() / "Timeline"
    with pytest.raises(AttributeError):
        application.workspace = tmp_path / "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        application.desktop = tmp_path / "other"  # type: ignore[misc]


def test_create_rejects_invalid_workspace_or_desktop(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace

    with pytest.raises(WorkspaceError, match="Desktop source does not exist"):
        DesktopApplication.create(
            workspace.root,
            desktop_path=tmp_path / "missing-desktop",
        )
    with pytest.raises(WorkspaceError, match="Workspace does not exist"):
        DesktopApplication.create(
            tmp_path / "missing-workspace",
            desktop_path=tmp_path,
        )


def test_assess_replaces_previous_session_and_status_is_fixed(
    tmp_path: Path,
) -> None:
    revealed: list[Path] = []
    application, workspace, desktop = application_setup(
        tmp_path,
        revealed=revealed,
    )
    source = old_file(desktop)

    first = application.assess()
    second = application.assess()
    report = application.status(scan_source=True)

    assert first.id != second.id
    assert second.assessment.entries[0].group is EvaluationGroup.ARCHIVE
    assert report.workspace == workspace
    assert report.pending_count == 1
    with pytest.raises(ValueError, match="expired"):
        application.reveal_item(first.id, source.name)
    assert application.reveal_item(second.id, source.name) == source
    assert revealed == [source]


def test_archive_is_selected_only_and_assessment_is_one_shot(
    tmp_path: Path,
) -> None:
    application, workspace, desktop = application_setup(tmp_path)
    selected = old_file(desktop, "selected.pdf")
    unselected = old_file(desktop, "unselected.pdf")
    session = application.assess()

    result = application.archive(session.id, [selected.name])

    target = workspace / "Timeline/2020/2020-07/selected.pdf"
    assert result.count(OperationStatus.MOVED) == 1
    assert not selected.exists()
    assert target.read_text(encoding="utf-8") == "desktop application test"
    assert unselected.exists()
    with pytest.raises(ValueError, match="expired"):
        application.archive(session.id, [unselected.name])


def test_invalid_selection_does_not_claim_current_assessment(tmp_path: Path) -> None:
    application, _workspace, desktop = application_setup(tmp_path)
    source = old_file(desktop)
    session = application.assess()

    with pytest.raises(ValueError, match="Select at least one"):
        application.archive(session.id, [])

    result = application.archive(session.id, [source.name])
    assert result.count(OperationStatus.MOVED) == 1


def test_trash_uses_injected_mover_and_claims_assessment(tmp_path: Path) -> None:
    trash = tmp_path / "Fake Trash"
    trash.mkdir()

    def fake_trash(path: Path) -> None:
        path.rename(trash / path.name)

    application, _workspace, desktop = application_setup(
        tmp_path,
        trasher=fake_trash,
    )
    cleanup = desktop / "unfinished.crdownload"
    cleanup.write_text("partial", encoding="utf-8")
    normal = old_file(desktop)
    session = application.assess()

    result = application.trash(session.id, [cleanup.name])

    assert result.count(OperationStatus.TRASHED) == 1
    assert (trash / cleanup.name).read_text(encoding="utf-8") == "partial"
    assert normal.exists()
    with pytest.raises(ValueError, match="expired"):
        application.trash(session.id, [cleanup.name])


def test_failed_action_still_consumes_assessment(tmp_path: Path) -> None:
    application, _workspace, desktop = application_setup(tmp_path)
    source = old_file(desktop)
    session = application.assess()

    with pytest.raises(ValueError, match="cleanup recommendation"):
        application.trash(session.id, [source.name])
    with pytest.raises(ValueError, match="expired"):
        application.archive(session.id, [source.name])


def test_undo_restores_archive_and_clears_assessment(tmp_path: Path) -> None:
    application, _workspace, desktop = application_setup(tmp_path)
    source = old_file(desktop)
    archived_session = application.assess()
    application.archive(archived_session.id, [source.name])
    current_session = application.assess()

    result = application.undo()

    assert result.count(OperationStatus.RESTORED) == 1
    assert source.read_text(encoding="utf-8") == "desktop application test"
    with pytest.raises(ValueError, match="expired"):
        application.reveal_item(current_session.id, source.name)


def test_open_folder_allows_only_desktop_and_timeline(tmp_path: Path) -> None:
    opened: list[Path] = []
    application, workspace, desktop = application_setup(
        tmp_path,
        opened=opened,
    )

    assert application.open_folder("desktop") == desktop
    assert application.open_folder("timeline") == workspace / "Timeline"
    with pytest.raises(ValueError, match="desktop.*timeline"):
        application.open_folder("../../Desktop")
    assert opened == [desktop, workspace / "Timeline"]


def test_reveal_requires_current_assessed_existing_top_level_item(
    tmp_path: Path,
) -> None:
    revealed: list[Path] = []
    application, _workspace, desktop = application_setup(
        tmp_path,
        revealed=revealed,
    )
    source = old_file(desktop)
    session = application.assess()

    with pytest.raises(ValueError, match="not in the current assessment"):
        application.reveal_item(session.id, "other.txt")
    with pytest.raises(ValueError, match="invalid"):
        application.reveal_item(session.id, "../report.pdf")
    source.unlink()
    with pytest.raises(ValueError, match="no longer exists"):
        application.reveal_item(session.id, source.name)
    assert revealed == []


def test_desktop_application_does_not_require_inbox(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    workspace.inbox.rmdir()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    old_file(desktop)

    application = DesktopApplication.create(
        workspace.root,
        desktop_path=desktop,
        opener=lambda _path: None,
        revealer=lambda _path: None,
        trasher=lambda _path: None,
    )

    assert len(application.assess().assessment.entries) == 1


def test_collect_all_uses_monthly_targets_without_item_selection(
    tmp_path: Path,
) -> None:
    application, workspace, desktop = application_setup(tmp_path)
    first = old_file(desktop, "first.pdf")
    second = old_file(desktop, "second.pdf")

    result = application.collect_all()

    assert result.count(OperationStatus.MOVED) == 2
    targets = {item.target for item in result.results if item.target is not None}
    assert {target.parent for target in targets} == {
        workspace / "Timeline/2020/2020-07"
    }
    assert all(target.is_relative_to(workspace / "Timeline") for target in targets)
    assert not first.exists()
    assert not second.exists()


def test_history_calendar_reads_desktop_batches_without_mutating_files(
    tmp_path: Path,
) -> None:
    application, workspace, desktop = application_setup(tmp_path)
    source = old_file(desktop)
    application.collect_all()
    archived = workspace / "Timeline/2020/2020-07/report.pdf"

    calendar = application.history_calendar()

    assert len(calendar.batches) == 1
    assert calendar.batches[0].undoable is True
    assert calendar.batches[0].items[0].source == source
    assert calendar.batches[0].items[0].destination == archived
    assert archived.exists()
    assert not source.exists()
