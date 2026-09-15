"""Isolated tests for the native Froganize macOS entry point."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from dropnest.desktop_app import DesktopApplication
from dropnest.macos_app import (
    application_support,
    configured_desktop,
    configured_workspace,
    default_workspace,
    run_application,
)


def test_default_workspace_prefers_existing_legacy_workspace(tmp_path: Path) -> None:
    home = tmp_path / "Home"
    legacy = home / "Documents" / "DropNestWorkspace"

    assert default_workspace(home) == home / "Documents" / "FroganizeWorkspace"

    legacy.mkdir(parents=True)
    assert default_workspace(home) == legacy


def test_paths_accept_isolated_packaging_overrides(tmp_path: Path) -> None:
    home = tmp_path / "Home"
    environment = {
        "FROGANIZE_WORKSPACE": str(tmp_path / "Workspace"),
        "FROGANIZE_DESKTOP": str(tmp_path / "Desktop Source"),
        "FROGANIZE_STATE_DIR": str(tmp_path / "State"),
    }

    assert configured_workspace(home, environment) == tmp_path / "Workspace"
    assert configured_desktop(home, environment) == tmp_path / "Desktop Source"
    assert application_support(home, environment) == tmp_path / "State"


def test_run_application_initializes_paths_and_starts_native_gui(
    tmp_path: Path,
) -> None:
    home = tmp_path / "Home"
    desktop = tmp_path / "Desktop Source"
    workspace = tmp_path / "Workspace"
    desktop.mkdir()
    environment = {
        "FROGANIZE_WORKSPACE": str(workspace),
        "FROGANIZE_DESKTOP": str(desktop),
        "FROGANIZE_STATE_DIR": str(tmp_path / "State"),
    }
    calls: list[tuple[Path, Path, Mapping[str, str]]] = []

    def fake_gui(
        application: DesktopApplication,
        *,
        environment: Mapping[str, str],
    ) -> int:
        calls.append((application.workspace, application.desktop, environment))
        return 17

    result = run_application(
        home=home,
        environment=environment,
        gui_runner=fake_gui,
    )

    assert result == 17
    assert calls == [(workspace.resolve(), desktop.resolve(), environment)]
    assert (workspace / "Inbox").is_dir()
    assert (workspace / "Timeline").is_dir()
    assert (workspace / ".dropnest" / "config.json").is_file()
    assert not (tmp_path / "State" / "server.json").exists()


def test_macos_entry_has_no_browser_or_http_server_runtime() -> None:
    source = Path(__file__).parents[1] / "src" / "dropnest" / "macos_app.py"
    text = source.read_text(encoding="utf-8")

    assert "webbrowser" not in text
    assert "create_web_server" not in text
    assert "serve_forever" not in text
    assert "server.json" not in text
