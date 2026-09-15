"""Safe synthetic demo generator tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dropnest.models import EvaluationGroup
from dropnest.planner import build_desktop_assessment
from scripts.create_demo import (
    AGE_BOUNDARY_MARGIN,
    DEFAULT_PORT,
    DEMO_ITEMS,
    MARKER_NAME,
    PROJECT_DEMO_NAME,
    DemoSafetyError,
    create_demo,
    resolve_demo_root,
)


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_demo_has_fixed_groups_cross_year_and_safe_conflict(
    tmp_path: Path,
) -> None:
    assert tuple(item.name for item in DEMO_ITEMS) == (
        "Fresh Screenshot.png",
        "Active Design",
        "Draft Presentation.pptx",
        "Reference Photos",
        "report.pdf",
        "Client Handoff",
        "Meeting Recording.mp4",
        "Downloads 2025.zip",
        ".DS_Store",
        "~unfinished-download.tmp",
        "Cloud Photo.jpg.icloud",
        "External Shortcut",
    )
    result = create_demo(tmp_path / "demo", now=NOW)
    assessment = build_desktop_assessment(
        result.workspace,
        desktop_path=result.desktop,
        now=NOW,
    )

    assert result.counts == {
        "recent": 2,
        "keep": 0,
        "archive": 6,
        "cleanup": 2,
        "unsafe": 2,
    }
    assert {
        group: assessment.count(group)
        for group in EvaluationGroup
    } == {
        EvaluationGroup.RECENT: 2,
        EvaluationGroup.KEEP: 0,
        EvaluationGroup.ARCHIVE: 6,
        EvaluationGroup.CLEANUP: 2,
        EvaluationGroup.UNSAFE: 2,
    }

    by_name = {
        entry.plan_entry.source.name: entry
        for entry in assessment.entries
    }
    assert by_name["report.pdf"].plan_entry.target is not None
    assert by_name["report.pdf"].plan_entry.target.name == "report (1).pdf"
    assert by_name["Downloads 2025.zip"].plan_entry.year is not None
    assert by_name["Downloads 2025.zip"].plan_entry.year < NOW.year
    assert by_name["Active Design"].group is EvaluationGroup.RECENT
    assert by_name[".DS_Store"].group is EvaluationGroup.CLEANUP
    assert by_name["~unfinished-download.tmp"].group is EvaluationGroup.CLEANUP
    assert by_name["External Shortcut"].group is EvaluationGroup.UNSAFE
    assert by_name["Cloud Photo.jpg.icloud"].group is EvaluationGroup.UNSAFE
    expected_ages = {
        item.name: item.age_days
        for item in DEMO_ITEMS
        if item.age_days is not None
    }
    assert {
        name: by_name[name].age_days
        for name in expected_ages
    } == expected_ages

    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["synthetic_only"] is True
    assert manifest["expected_counts"] == result.counts
    assert manifest["expected_conflict_target"].endswith("report (1).pdf")
    assert result.browser_url == f"http://127.0.0.1:{DEFAULT_PORT}"
    assert "--desktop" in result.start_command
    assert str(result.desktop) in result.start_command


def test_demo_age_boundaries_survive_timestamp_rounding(
    tmp_path: Path,
) -> None:
    result = create_demo(tmp_path / "demo", now=NOW)
    slightly_earlier = NOW - AGE_BOUNDARY_MARGIN / 2

    assessment = build_desktop_assessment(
        result.workspace,
        desktop_path=result.desktop,
        now=slightly_earlier,
    )
    by_name = {
        entry.plan_entry.source.name: entry
        for entry in assessment.entries
    }

    for item in DEMO_ITEMS:
        if item.age_days is not None:
            assert by_name[item.name].age_days == item.age_days


def test_reset_is_idempotent_and_requires_a_matching_marker(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    first = create_demo(target, now=NOW)
    rogue = first.desktop / "not-part-of-demo.txt"
    rogue.write_text("remove only after marker verification", encoding="utf-8")

    rebuilt = create_demo(target, reset=True, now=NOW)

    assert rebuilt.counts == first.counts
    assert not rogue.exists()
    assert (target / MARKER_NAME).is_file()
    assert len(tuple(rebuilt.desktop.iterdir())) == 12

    unmarked = tmp_path / "ordinary-directory"
    unmarked.mkdir()
    important = unmarked / "keep-me.txt"
    important.write_text("untouched", encoding="utf-8")
    with pytest.raises(DemoSafetyError, match="unmarked"):
        create_demo(unmarked, reset=True, now=NOW)
    assert important.read_text(encoding="utf-8") == "untouched"


@pytest.mark.parametrize(
    "dangerous",
    (
        Path("/"),
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Desktop" / "nested-demo",
    ),
)
def test_real_root_home_and_desktop_are_never_accepted(
    dangerous: Path,
) -> None:
    with pytest.raises(DemoSafetyError):
        resolve_demo_root(dangerous, force_project_demo=True)


def test_path_traversal_and_non_dedicated_project_paths_are_rejected(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    fake_temp = tmp_path / "system-temp"
    fake_temp.mkdir()

    with pytest.raises(DemoSafetyError, match=r"\.\."):
        resolve_demo_root(
            project / ".." / "escape",
            project_root=project,
            temp_root=fake_temp,
        )
    with pytest.raises(DemoSafetyError, match="force-project-demo"):
        resolve_demo_root(
            project / "public-demo",
            force_project_demo=True,
            project_root=project,
            temp_root=fake_temp,
        )

    approved = resolve_demo_root(
        None,
        force_project_demo=True,
        project_root=project,
        temp_root=fake_temp,
    )
    assert approved == project / PROJECT_DEMO_NAME


def test_reset_never_reads_or_follows_an_external_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "demo"
    result = create_demo(target, now=NOW)
    outside = tmp_path / "private-user-file.txt"
    outside.write_text("private and unchanged", encoding="utf-8")

    link = result.desktop / "External Shortcut"
    link.unlink()
    link.symlink_to(outside)
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == outside:
            raise AssertionError("demo generator tried to read an external file")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    create_demo(target, reset=True, now=NOW)

    assert original_read_text(outside, encoding="utf-8") == "private and unchanged"
