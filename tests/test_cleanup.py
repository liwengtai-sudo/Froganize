"""Conservative Desktop cleanup recommendations and Trash execution tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from dropnest.cleanup import (
    execute_cleanup_recommendations,
    move_to_macos_trash,
)
from dropnest.models import EvaluationGroup, ItemType, OperationStatus, PlanStatus
from dropnest.planner import build_desktop_assessment
from dropnest.workspace import initialize_workspace


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def setup_desktop(tmp_path: Path):
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    return workspace, desktop


def set_age(path: Path, days: int) -> None:
    timestamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp), follow_symlinks=False)


def assess(workspace, desktop: Path):
    return build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=NOW,
    )


def test_only_high_confidence_regular_files_are_recommended(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    recommended = (
        ".DS_Store",
        "~draft.docx",
        "cache.tmp",
        "movie.download",
        "transfer.crdownload",
        "segment.part",
    )
    for name in recommended:
        source = desktop / name
        source.write_text("temporary", encoding="utf-8")
        set_age(source, 3)
    (desktop / ".notes").write_text("keep", encoding="utf-8")
    (desktop / ".private.tmp").write_text("keep", encoding="utf-8")
    (desktop / "Cloud Photo.jpg.icloud").write_text("placeholder", encoding="utf-8")
    (desktop / "folder.tmp").mkdir()
    (desktop / "linked.tmp").symlink_to(tmp_path / "outside.tmp")

    assessment = assess(workspace, desktop)
    entries = {
        item.plan_entry.source.name: item
        for item in assessment.entries
    }

    assert assessment.count(EvaluationGroup.CLEANUP) == len(recommended)
    for name in recommended:
        entry = entries[name]
        assert entry.group is EvaluationGroup.CLEANUP
        assert entry.default_selected is False
        assert entry.plan_entry.status is PlanStatus.SKIPPED
        assert entry.plan_entry.item_type is ItemType.FILE
        assert entry.plan_entry.reason_code.startswith("cleanup_")
    assert entries[".notes"].group is EvaluationGroup.UNSAFE
    assert entries[".private.tmp"].group is EvaluationGroup.UNSAFE
    assert entries["Cloud Photo.jpg.icloud"].group is EvaluationGroup.UNSAFE
    assert entries["folder.tmp"].group is not EvaluationGroup.CLEANUP
    assert entries["linked.tmp"].group is EvaluationGroup.UNSAFE


def test_selected_recommendation_moves_only_to_injected_temp_trash(
    tmp_path: Path,
) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    candidate = desktop / "cache.tmp"
    candidate.write_text("temporary", encoding="utf-8")
    normal = desktop / "report.pdf"
    normal.write_text("important", encoding="utf-8")
    trash = tmp_path / "Fake Trash"
    trash.mkdir()
    assessment = assess(workspace, desktop)

    result = execute_cleanup_recommendations(
        assessment,
        (candidate.name,),
        trash_mover=lambda path: path.rename(trash / path.name),
    )

    assert result.count(OperationStatus.TRASHED) == 1
    assert result.count(OperationStatus.FAILED) == 0
    assert not candidate.exists()
    assert (trash / candidate.name).read_text(encoding="utf-8") == "temporary"
    assert normal.read_text(encoding="utf-8") == "important"


def test_non_recommended_item_is_rejected_before_any_move(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    normal = desktop / "report.pdf"
    normal.write_text("important", encoding="utf-8")
    assessment = assess(workspace, desktop)
    called: list[Path] = []

    with pytest.raises(ValueError, match="not in the cleanup recommendation"):
        execute_cleanup_recommendations(
            assessment,
            (normal.name,),
            trash_mover=called.append,
        )

    assert called == []
    assert normal.exists()


def test_changed_candidate_fails_without_calling_trash(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    candidate = desktop / "cache.tmp"
    candidate.write_text("one", encoding="utf-8")
    assessment = assess(workspace, desktop)
    called: list[Path] = []

    result = execute_cleanup_recommendations(
        assessment,
        (candidate.name,),
        before_each=lambda _entry: candidate.write_text("changed", encoding="utf-8"),
        trash_mover=called.append,
    )

    assert result.count(OperationStatus.FAILED) == 1
    assert result.results[0].reason_code == "source_changed"
    assert called == []
    assert candidate.read_text(encoding="utf-8") == "changed"


def test_symlink_replacement_is_blocked_without_touching_target(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    candidate = desktop / "cache.tmp"
    candidate.write_text("temporary", encoding="utf-8")
    outside = tmp_path / "outside.tmp"
    outside.write_text("outside", encoding="utf-8")
    assessment = assess(workspace, desktop)
    called: list[Path] = []

    def replace_with_link(_entry) -> None:
        candidate.unlink()
        candidate.symlink_to(outside)

    result = execute_cleanup_recommendations(
        assessment,
        (candidate.name,),
        before_each=replace_with_link,
        trash_mover=called.append,
    )

    assert result.count(OperationStatus.FAILED) == 1
    assert result.results[0].reason_code == "safety_error"
    assert called == []
    assert outside.read_text(encoding="utf-8") == "outside"


def test_one_trash_failure_does_not_block_other_candidates(tmp_path: Path) -> None:
    workspace, desktop = setup_desktop(tmp_path)
    first = desktop / "first.tmp"
    second = desktop / "second.part"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    trash = tmp_path / "Fake Trash"
    trash.mkdir()
    assessment = assess(workspace, desktop)

    def trash_mover(path: Path) -> None:
        if path == first:
            raise OSError("simulated Finder failure")
        path.rename(trash / path.name)

    result = execute_cleanup_recommendations(
        assessment,
        (first.name, second.name),
        trash_mover=trash_mover,
    )

    assert result.count(OperationStatus.FAILED) == 1
    assert result.count(OperationStatus.TRASHED) == 1
    assert first.exists()
    assert (trash / second.name).exists()


def test_macos_trash_uses_argv_instead_of_interpolating_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []
    unsafe_text = Path('/tmp/name "with quote"\nand newline.tmp')

    def fake_run(arguments, **_kwargs):
        captured.append(arguments)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("dropnest.cleanup.sys.platform", "darwin")
    monkeypatch.setattr("dropnest.cleanup.subprocess.run", fake_run)

    move_to_macos_trash(unsafe_text)

    assert captured[0][-1] == str(unsafe_text)
    assert str(unsafe_text) not in captured[0][2]
