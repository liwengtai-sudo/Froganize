#!/usr/bin/env python3
"""Capture the current native dashboard with synthetic temporary files only."""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dropnest.desktop_app import DesktopApplication  # noqa: E402
from dropnest.gui import FroganizeWindow  # noqa: E402
from dropnest.intelligence_history import IntelligencePaths  # noqa: E402
from dropnest.workspace import initialize_workspace  # noqa: E402


def _set_mtime(path: Path, value: datetime) -> None:
    timestamp = value.timestamp()
    os.utime(path, (timestamp, timestamp))


def _wait_for_dashboard(app: QApplication, window: FroganizeWindow) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        app.processEvents()
        if not window._busy and window._assessment is not None:
            return
        time.sleep(0.01)
    raise RuntimeError("The synthetic native dashboard did not finish rendering.")


def capture(output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="froganize-public-preview-") as raw:
        root = Path(raw)
        workspace = initialize_workspace(root / "FroganizeWorkspace").workspace
        desktop = root / "Desktop"
        desktop.mkdir()

        report = desktop / "Quarterly Review.pdf"
        report.write_text("synthetic report\n", encoding="utf-8")
        _set_mtime(report, datetime(2026, 7, 18, 10, 30, tzinfo=UTC))

        notes = desktop / "Meeting Notes.txt"
        notes.write_text("synthetic notes\n", encoding="utf-8")
        _set_mtime(notes, datetime(2026, 8, 3, 14, 15, tzinfo=UTC))

        project = desktop / "Launch Assets"
        project.mkdir()
        brief = project / "README.txt"
        brief.write_text("synthetic folder\n", encoding="utf-8")
        _set_mtime(brief, datetime(2026, 6, 24, 9, 0, tzinfo=UTC))
        _set_mtime(project, datetime(2026, 6, 24, 9, 0, tzinfo=UTC))

        (desktop / ".DS_Store").write_text("synthetic hidden item\n", encoding="utf-8")
        (desktop / "unfinished.crdownload").write_text(
            "synthetic incomplete download\n", encoding="utf-8"
        )

        backend = DesktopApplication.create(
            workspace.root,
            desktop_path=desktop,
            opener=lambda _path: None,
            revealer=lambda _path: None,
            trasher=lambda _path: None,
        )
        app = QApplication.instance() or QApplication([])
        window = FroganizeWindow(
            backend,
            auto_assess=False,
            environment={"FROGANIZE_STATE_DIR": str(root / "Application Support")},
            intelligence_paths=IntelligencePaths.from_root(root / "Intelligence"),
        )
        window.resize(1200, 800)
        window.show()
        window.refresh_assessment()
        _wait_for_dashboard(app, window)
        app.processEvents()

        output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(output), "PNG"):
            raise RuntimeError(f"Could not save native preview to {output}.")
        window.close()
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("media/github/native-dashboard.png"),
    )
    args = parser.parse_args()
    capture(args.output.expanduser().resolve())
    print(f"Synthetic native preview written to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
