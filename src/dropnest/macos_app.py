"""Self-contained native macOS application entry point for Froganize.

The distributable bundle opens a real Qt application window and calls the
same filesystem-safety core as the CLI.  It never starts an HTTP server,
claims a port, or opens a browser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from dropnest.desktop_app import DesktopApplication
from dropnest.exceptions import DropNestError
from dropnest.workspace import initialize_workspace

APP_SUPPORT_NAME = "Froganize"
DEFAULT_WORKSPACE_NAME = "FroganizeWorkspace"
LEGACY_WORKSPACE_NAME = "DropNestWorkspace"


class GuiRunner(Protocol):
    """Injectable native-window runner used by isolated startup tests."""

    def __call__(
        self,
        application: DesktopApplication,
        *,
        environment: Mapping[str, str],
    ) -> int: ...


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def default_workspace(home: Path) -> Path:
    """Prefer an existing legacy workspace, otherwise use the Froganize name."""
    documents = _resolved(home) / "Documents"
    legacy = documents / LEGACY_WORKSPACE_NAME
    if legacy.is_dir() and not legacy.is_symlink():
        return legacy
    return documents / DEFAULT_WORKSPACE_NAME


def configured_workspace(home: Path, environment: Mapping[str, str]) -> Path:
    """Return the explicit QA override or the safe per-user default."""
    override = environment.get("FROGANIZE_WORKSPACE")
    if override:
        return _resolved(Path(override))
    return default_workspace(home)


def configured_desktop(home: Path, environment: Mapping[str, str]) -> Path:
    """Return the explicit QA override or the user's Desktop."""
    override = environment.get("FROGANIZE_DESKTOP")
    if override:
        return _resolved(Path(override))
    return _resolved(home) / "Desktop"


def application_support(home: Path, environment: Mapping[str, str]) -> Path:
    """Return the private directory reserved for future app-only state."""
    override = environment.get("FROGANIZE_STATE_DIR")
    if override:
        return _resolved(Path(override))
    return _resolved(home) / "Library" / "Application Support" / APP_SUPPORT_NAME


def _run_native_gui(
    application: DesktopApplication,
    *,
    environment: Mapping[str, str],
) -> int:
    """Import Qt only for the desktop bundle, keeping the CLI dependency-light."""
    from dropnest.gui import run_gui

    return run_gui(application, environment=environment)


def show_error_dialog(message: str) -> None:
    """Display a concise native error dialog without interpolating shell text."""
    if sys.platform != "darwin":
        return
    script = (
        "on run argv\n"
        'display dialog (item 1 of argv) with title "Froganize" '
        'buttons {"好"} default button "好" with icon stop\n'
        "end run"
    )
    subprocess.run(
        ["/usr/bin/osascript", "-e", script, message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_application(
    *,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
    gui_runner: GuiRunner | None = None,
) -> int:
    """Initialize safe local paths and enter the native GUI event loop."""
    effective_home = _resolved(home or Path.home())
    effective_environment = os.environ if environment is None else environment
    workspace_path = configured_workspace(effective_home, effective_environment)
    desktop_path = configured_desktop(effective_home, effective_environment)

    workspace = initialize_workspace(workspace_path).workspace
    application = DesktopApplication.create(
        workspace.root,
        desktop_path=desktop_path,
    )
    runner = gui_runner or _run_native_gui
    return int(runner(application, environment=effective_environment))


def main() -> int:
    """Run the macOS GUI with concise native failure reporting."""
    try:
        return run_application()
    except (DropNestError, ImportError, OSError, RuntimeError, ValueError) as exc:
        show_error_dialog(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
