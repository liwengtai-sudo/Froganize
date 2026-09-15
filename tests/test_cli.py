"""Tests for the minimal DropNest command-line interface."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import dropnest
import pytest
from dropnest.cli import EXIT_FATAL, EXIT_PARTIAL, main
from dropnest.exceptions import WorkspaceError
from dropnest.models import BatchResult, OperationResult, OperationStatus
from dropnest.workspace import WorkspaceLock, validate_workspace


def run_installed_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the console script installed beside the active Python interpreter."""
    executable = Path(sys.executable).with_name("dropnest")
    return subprocess.run(
        [str(executable), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_package_can_be_imported() -> None:
    assert dropnest.__name__ == "dropnest"


def test_version_is_correct() -> None:
    assert dropnest.__version__ == "0.3.0"


def test_version_command_runs() -> None:
    result = run_installed_command("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == "Froganize 0.3.0"
    assert result.stderr == ""


def test_help_command_runs() -> None:
    result = run_installed_command("--help")

    assert result.returncode == 0
    assert "usage: dropnest" in result.stdout
    assert "--version" in result.stdout
    assert "Inbox" in result.stdout
    assert result.stderr == ""


def test_web_help_and_invalid_port_are_concise() -> None:
    helped = run_installed_command("web", "--help")
    invalid = run_installed_command("web", "--port", "70000", "/not-used")

    assert helped.returncode == 0
    assert "--no-browser" in helped.stdout
    assert "127.0.0.1" in helped.stdout
    assert invalid.returncode == 2
    assert "port must be between 0 and 65535" in invalid.stderr
    assert "Traceback" not in invalid.stderr


def test_init_preview_sort_status_and_undo_with_space_in_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "DropNest Test Workspace"

    initialized = run_installed_command("init", str(root))
    assert initialized.returncode == 0
    assert (root / "Inbox").is_dir()

    source = root / "Inbox" / "report.pdf"
    source.write_text("report", encoding="utf-8")
    timestamp = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    source.touch()
    __import__("os").utime(source, (timestamp, timestamp))

    previewed = run_installed_command("preview", str(root))
    assert previewed.returncode == 0
    assert str(source) in previewed.stdout
    assert "Timeline/2026/2026-07/report.pdf" in previewed.stdout
    assert source.exists()
    assert list((root / "Timeline").iterdir()) == []
    assert (root / ".dropnest/history.jsonl").read_text(encoding="utf-8") == ""

    sorted_result = run_installed_command("sort", str(root))
    assert sorted_result.returncode == 0
    assert "Moved: 1" in sorted_result.stdout

    status = run_installed_command("status", str(root))
    assert status.returncode == 0
    assert "Latest moved: 1" in status.stdout

    undone = run_installed_command("undo", str(root))
    assert undone.returncode == 0
    assert "Restored: 1" in undone.stdout
    assert source.exists()


def test_fatal_cli_error_is_concise_without_traceback(
    tmp_path: Path,
) -> None:
    result = run_installed_command("preview", str(tmp_path / "missing"))

    assert result.returncode == EXIT_FATAL
    assert result.stderr.startswith("Error:")
    assert "Traceback" not in result.stderr


def test_status_invalid_workspace_uses_partial_exit_code(tmp_path: Path) -> None:
    result = run_installed_command("status", str(tmp_path / "missing"))

    assert result.returncode == EXIT_PARTIAL
    assert "Valid: no" in result.stdout


def test_partial_sort_result_uses_partial_exit_code(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    failed = OperationResult(
        tmp_path / "source",
        tmp_path / "target",
        OperationStatus.FAILED,
        "target_conflict",
        "occupied",
    )
    batch = BatchResult("batch", (failed,))
    fake_plan = type(
        "Plan",
        (),
        {"workspace": type("Workspace", (), {"timeline": tmp_path / "archive"})()},
    )()
    monkeypatch.setattr(
        "dropnest.cli.sort_workspace",
        lambda workspace: (fake_plan, batch),
    )

    exit_code = main(["sort", str(tmp_path / "not-read")])

    assert exit_code == EXIT_PARTIAL
    assert "Failed: 1" in capsys.readouterr().out


def test_mutating_cli_reports_workspace_lock_conflict(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    assert run_installed_command("init", str(root)).returncode == 0
    workspace = validate_workspace(root)

    with WorkspaceLock(workspace):
        result = run_installed_command("sort", str(root))

    assert result.returncode == EXIT_FATAL
    assert "locked by another operation" in result.stderr


def test_debug_mode_reraises_expected_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        main(["--debug", "preview", str(tmp_path / "missing")])
