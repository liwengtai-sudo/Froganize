"""Read-only scanning, classification, and conflict-planning tests."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dropnest.conflict import available_name
from dropnest.models import ItemType, PlanLayout, PlanStatus
from dropnest.planner import build_desktop_collection_plan, build_plan
from dropnest.workspace import initialize_workspace


def workspace_at(tmp_path: Path) -> Path:
    return initialize_workspace(tmp_path / "workspace").workspace.root


def set_mtime(path: Path, moment: datetime) -> None:
    timestamp = moment.timestamp()
    os.utime(path, (timestamp, timestamp))


def fixed_time(moment: datetime):
    return lambda metadata: moment


def test_empty_inbox_has_empty_plan(tmp_path: Path) -> None:
    plan = build_plan(workspace_at(tmp_path))

    assert plan.entries == ()


def test_file_is_classified_by_year_and_month(tmp_path: Path) -> None:
    root = workspace_at(tmp_path)
    source = root / "Inbox" / "report.pdf"
    source.touch()
    moment = datetime(2026, 7, 19, 10, 30, tzinfo=UTC)

    entry = build_plan(root, time_policy=fixed_time(moment)).entries[0]

    assert entry.status is PlanStatus.PLANNED
    assert entry.item_type is ItemType.FILE
    assert entry.year == 2026
    assert entry.month == 7
    assert entry.classification_time == moment
    assert entry.target == root / "Timeline/2026/2026-07/report.pdf"


def test_folder_is_one_whole_planned_item(tmp_path: Path) -> None:
    root = workspace_at(tmp_path)
    folder = root / "Inbox" / "ResearchProject"
    folder.mkdir()
    (folder / "nested.txt").write_text("nested", encoding="utf-8")

    plan = build_plan(
        root,
        time_policy=fixed_time(datetime(2025, 11, 2, tzinfo=UTC)),
    )

    assert len(plan.entries) == 1
    assert plan.entries[0].source == folder
    assert plan.entries[0].item_type is ItemType.DIRECTORY
    assert plan.entries[0].target == (
        root / "Timeline/2025/2025-11/ResearchProject"
    )


def test_default_policy_uses_local_timezone_across_year_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not hasattr(time, "tzset"):
        pytest.skip("platform does not support tzset")
    root = workspace_at(tmp_path)
    source = root / "Inbox" / "new-year.txt"
    source.touch()
    set_mtime(source, datetime(2025, 12, 31, 18, 0, tzinfo=UTC))
    old_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Etc/GMT-8")
    time.tzset()
    try:
        entry = build_plan(root).entries[0]
    finally:
        if old_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", old_tz)
        time.tzset()

    assert (entry.year, entry.month) == (2026, 1)


@pytest.mark.parametrize(
    ("name", "reason_code"),
    [
        (".DS_Store", "hidden"),
        (".gitkeep", "hidden"),
        (".secret", "hidden"),
        ("~draft.docx", "temporary"),
        ("download.tmp", "temporary"),
        ("download.TMP", "temporary"),
        ("photo.jpg.icloud", "cloud_placeholder"),
    ],
)
def test_default_skip_rules(
    tmp_path: Path,
    name: str,
    reason_code: str,
) -> None:
    root = workspace_at(tmp_path)
    (root / "Inbox" / name).touch()

    entry = build_plan(root).entries[0]

    assert entry.status is PlanStatus.SKIPPED
    assert entry.reason_code == reason_code
    assert entry.reason


def test_tmp_directory_is_not_skipped_by_file_suffix_rule(tmp_path: Path) -> None:
    root = workspace_at(tmp_path)
    (root / "Inbox" / "Project.tmp").mkdir()

    entry = build_plan(root).entries[0]

    assert entry.status is PlanStatus.PLANNED
    assert entry.item_type is ItemType.DIRECTORY


def test_symbolic_link_is_skipped_without_following(tmp_path: Path) -> None:
    root = workspace_at(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "Inbox" / "link.txt").symlink_to(outside)

    entry = build_plan(root).entries[0]

    assert entry.status is PlanStatus.SKIPPED
    assert entry.reason_code == "symbolic_link"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_unreadable_item_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = workspace_at(tmp_path)
    source = root / "Inbox" / "private.txt"
    source.touch()
    real_access = os.access

    def fake_access(path: os.PathLike[str], mode: int) -> bool:
        if Path(path) == source and mode == os.R_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    entry = build_plan(root).entries[0]

    assert entry.status is PlanStatus.SKIPPED
    assert entry.reason_code == "unreadable"


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("report.pdf", ["report.pdf"], "report (1).pdf"),
        ("archive.tar.gz", ["archive.tar.gz"], "archive (1).tar.gz"),
        ("README", ["README"], "README (1)"),
        ("Project", ["Project"], "Project (1)"),
        ("report.pdf", ["REPORT.PDF"], "report (1).pdf"),
        (
            "report.pdf",
            ["report.pdf", "report (1).pdf", "report (2).pdf"],
            "report (3).pdf",
        ),
    ],
)
def test_conflict_names_are_safe_and_preserve_suffixes(
    tmp_path: Path,
    name: str,
    existing: list[str],
    expected: str,
) -> None:
    root = workspace_at(tmp_path)
    source = root / "Inbox" / name
    if name == "Project":
        source.mkdir()
    else:
        source.touch()
    month = root / "Timeline/2026/2026-07"
    month.mkdir(parents=True)
    for occupied in existing:
        (month / occupied).touch()

    entry = build_plan(
        root,
        time_policy=fixed_time(datetime(2026, 7, 1, tzinfo=UTC)),
    ).entries[0]

    assert entry.target is not None
    assert entry.target.name == expected
    assert entry.renamed_from == name


def test_plan_order_and_in_plan_casefold_reservations_are_deterministic(
    tmp_path: Path,
) -> None:
    root = workspace_at(tmp_path)
    (root / "Inbox" / "alpha.txt").touch()
    (root / "Inbox" / "zeta.txt").touch()
    policy = fixed_time(datetime(2026, 4, 1, tzinfo=UTC))

    first = build_plan(root, time_policy=policy)
    second = build_plan(root, time_policy=policy)

    assert [entry.source.name for entry in first.entries] == [
        "alpha.txt",
        "zeta.txt",
    ]
    assert [entry.target.name for entry in first.entries if entry.target] == [
        "alpha.txt",
        "zeta.txt",
    ]
    assert [entry.target for entry in first.entries] == [
        entry.target for entry in second.entries
    ]


def test_casefolded_names_are_reserved_across_one_plan() -> None:
    occupied: set[str] = set()

    first = available_name("ALPHA.TXT", ItemType.FILE, occupied)
    second = available_name("alpha.txt", ItemType.FILE, occupied)

    assert first == ("ALPHA.TXT", False)
    assert second == ("alpha (1).txt", True)


def test_planner_does_not_create_timeline_directories(tmp_path: Path) -> None:
    root = workspace_at(tmp_path)
    (root / "Inbox" / "report.pdf").touch()

    build_plan(
        root,
        time_policy=fixed_time(datetime(2026, 7, 1, tzinfo=UTC)),
    )

    assert list((root / "Timeline").iterdir()) == []


def test_desktop_collection_routes_each_item_by_last_modified_month(
    tmp_path: Path,
) -> None:
    root = workspace_at(tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    report = desktop / "report.pdf"
    report.write_text("report", encoding="utf-8")
    project = desktop / "Project"
    project.mkdir()
    notes = project / "notes.txt"
    notes.write_text("notes", encoding="utf-8")
    report_time = datetime(2025, 12, 15, 12, 0, tzinfo=UTC)
    project_time = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    set_mtime(report, report_time)
    set_mtime(notes, project_time)
    set_mtime(project, datetime(2024, 1, 1, 12, 0, tzinfo=UTC))
    collected_at = datetime(2026, 9, 1, 15, 30, tzinfo=UTC)

    plan = build_desktop_collection_plan(
        root,
        desktop_path=desktop,
        collected_at=collected_at,
    )

    assert plan.layout is PlanLayout.MONTHLY
    assert plan.source_root == desktop.resolve()
    assert [entry.source.name for entry in plan.entries] == ["Project", "report.pdf"]
    planned = [entry for entry in plan.entries if entry.status is PlanStatus.PLANNED]
    by_name = {entry.source.name: entry for entry in planned}
    assert by_name["report.pdf"].target == (
        root / "Timeline/2025/2025-12/report.pdf"
    )
    assert by_name["report.pdf"].classification_time == report_time
    assert by_name["Project"].target == root / "Timeline/2026/2026-07/Project"
    assert by_name["Project"].classification_time == project_time
    assert plan.generated_at == collected_at
    assert list((root / "Timeline").iterdir()) == []


def test_desktop_collection_leaves_launcher_hidden_temporary_and_links(
    tmp_path: Path,
) -> None:
    root = workspace_at(tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "FROGANIZE.APP").mkdir()
    (desktop / "Froganize Beta.app").mkdir()
    partial_bundle = desktop / "unfinished.download"
    partial_bundle.mkdir()
    (partial_bundle / "payload").write_text("partial", encoding="utf-8")
    (desktop / ".hidden").write_text("hidden", encoding="utf-8")
    (desktop / "unfinished.crdownload").write_text("partial", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (desktop / "linked.txt").symlink_to(outside)
    (desktop / "keep.txt").write_text("keep", encoding="utf-8")

    plan = build_desktop_collection_plan(
        root,
        desktop_path=desktop,
        collected_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
    )

    by_name = {entry.source.name: entry for entry in plan.entries}
    assert "FROGANIZE.APP" not in by_name
    assert "Froganize Beta.app" not in by_name
    assert by_name["keep.txt"].status is PlanStatus.PLANNED
    assert by_name[".hidden"].reason_code == "hidden"
    assert by_name["unfinished.crdownload"].reason_code == "cleanup_partial_download"
    assert by_name["unfinished.download"].reason_code == "cleanup_partial_download"
    assert by_name["linked.txt"].reason_code == "symbolic_link"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_desktop_collection_avoids_existing_monthly_name_case_insensitively(
    tmp_path: Path,
) -> None:
    root = workspace_at(tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    report = desktop / "report.pdf"
    report.touch()
    set_mtime(report, datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    target_month = root / "Timeline/2026/2026-09"
    target_month.mkdir(parents=True)
    (target_month / "REPORT.PDF").touch()

    plan = build_desktop_collection_plan(
        root,
        desktop_path=desktop,
        collected_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
    )

    assert plan.entries[0].target == target_month / "report (1).pdf"
