"""Controlled end-to-end dogfooding using only pytest temporary directories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def run_dropnest(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the installed console command from the active test environment."""
    executable = Path(sys.executable).with_name("dropnest")
    return subprocess.run(
        [str(executable), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def set_mtime(path: Path, year: int, month: int) -> None:
    timestamp = datetime(year, month, 15, 12, 0, tzinfo=UTC).timestamp()
    os.utime(path, (timestamp, timestamp))


def tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    """Capture names, file bytes, and symlink targets without following links."""
    result: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes())
        else:
            result[relative] = ("directory", None)
    return result


def test_realistic_cli_workflow_is_safe_and_reversible(tmp_path: Path) -> None:
    """Exercise the complete MVP with heterogeneous, disposable Inbox items."""
    workspace = tmp_path / "DropNest Dogfood Workspace"
    initialized = run_dropnest("init", str(workspace))
    assert initialized.returncode == 0, initialized.stderr

    report = workspace / "Inbox/report.pdf"
    report.write_bytes(b"REPORT_PAYLOAD_41A")
    set_mtime(report, 2026, 5)

    screenshot = workspace / "Inbox/screenshot.png"
    screenshot.write_bytes(b"PNG_PAYLOAD_82B")
    set_mtime(screenshot, 2026, 6)

    archive = workspace / "Inbox/research-data.tar.gz"
    archive.write_bytes(b"ARCHIVE_PAYLOAD_73C")
    set_mtime(archive, 2026, 7)

    project = workspace / "Inbox/Old Project"
    project.mkdir()
    nested = project / "src/main.py"
    nested.parent.mkdir()
    nested.write_text("print('nested project stays intact')", encoding="utf-8")
    set_mtime(project, 2025, 11)

    (workspace / "Inbox/.DS_Store").write_bytes(b"hidden")
    (workspace / "Inbox/~draft.docx").write_bytes(b"temporary")
    (workspace / "Inbox/transfer.tmp").write_bytes(b"incomplete")
    (workspace / "Inbox/photo.jpg.icloud").write_bytes(b"placeholder")
    external_target = tmp_path / "external-target.txt"
    external_target.write_text("must remain untouched", encoding="utf-8")
    (workspace / "Inbox/external-link").symlink_to(external_target)

    occupied_month = workspace / "Timeline/2026/2026-07"
    occupied_month.mkdir(parents=True)
    occupied = occupied_month / "research-data.tar.gz"
    occupied.write_bytes(b"EXISTING_ARCHIVE_MUST_SURVIVE")

    before_preview = tree_snapshot(workspace)
    preview = run_dropnest("preview", str(workspace))
    after_preview = tree_snapshot(workspace)

    assert preview.returncode == 0, preview.stderr
    assert "Planned: 4" in preview.stdout
    assert "Skipped: 5" in preview.stdout
    assert "Failed: 0" in preview.stdout
    assert "Timeline/2026/2026-05/report.pdf" in preview.stdout
    assert "Timeline/2026/2026-06/screenshot.png" in preview.stdout
    assert "Timeline/2026/2026-07/research-data (1).tar.gz" in preview.stdout
    assert "Timeline/2025/2025-11/Old Project" in preview.stdout
    assert "symbolic links are skipped" in preview.stdout
    assert "iCloud placeholder files are skipped" in preview.stdout
    assert before_preview == after_preview

    sorted_result = run_dropnest("sort", str(workspace))

    assert sorted_result.returncode == 0, sorted_result.stderr
    assert "Moved: 4" in sorted_result.stdout
    assert "Skipped: 5" in sorted_result.stdout
    assert "Failed: 0" in sorted_result.stdout
    assert (workspace / "Timeline/2026/2026-05/report.pdf").read_bytes() == (
        b"REPORT_PAYLOAD_41A"
    )
    assert (workspace / "Timeline/2026/2026-06/screenshot.png").read_bytes() == (
        b"PNG_PAYLOAD_82B"
    )
    renamed_archive = (
        workspace / "Timeline/2026/2026-07/research-data (1).tar.gz"
    )
    assert renamed_archive.read_bytes() == b"ARCHIVE_PAYLOAD_73C"
    assert occupied.read_bytes() == b"EXISTING_ARCHIVE_MUST_SURVIVE"
    moved_project = workspace / "Timeline/2025/2025-11/Old Project"
    assert (moved_project / "src/main.py").read_text(encoding="utf-8") == (
        "print('nested project stays intact')"
    )
    assert external_target.read_text(encoding="utf-8") == "must remain untouched"

    history_path = workspace / ".dropnest/history.jsonl"
    sort_records = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(sort_records) == 4
    assert all(record["event_type"] == "sort" for record in sort_records)
    history_text = history_path.read_text(encoding="utf-8")
    assert "REPORT_PAYLOAD_41A" not in history_text
    assert "ARCHIVE_PAYLOAD_73C" not in history_text

    status = run_dropnest("status", str(workspace))

    assert status.returncode == 0, status.stderr
    assert "Valid: yes" in status.stdout
    assert "Inbox items: 5" in status.stdout
    assert "Sortable: 0" in status.stdout
    assert "Skipped: 5" in status.stdout
    assert "Archive months: 4" in status.stdout
    assert "Latest moved: 4" in status.stdout
    assert "Latest undo: not_started" in status.stdout

    undone = run_dropnest("undo", str(workspace))

    assert undone.returncode == 0, undone.stderr
    assert "Restored: 4" in undone.stdout
    assert "Failed: 0" in undone.stdout
    assert report.read_bytes() == b"REPORT_PAYLOAD_41A"
    assert screenshot.read_bytes() == b"PNG_PAYLOAD_82B"
    assert archive.read_bytes() == b"ARCHIVE_PAYLOAD_73C"
    assert nested.read_text(encoding="utf-8") == (
        "print('nested project stays intact')"
    )
    assert occupied.read_bytes() == b"EXISTING_ARCHIVE_MUST_SURVIVE"

    repeated = run_dropnest("undo", str(workspace))

    assert repeated.returncode == 0
    assert "Nothing to undo" in repeated.stdout
    all_records = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(all_records) == 8
    assert sum(record["event_type"] == "undo" for record in all_records) == 4
