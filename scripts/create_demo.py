#!/usr/bin/env python3
"""Create a safe, synthetic Froganize Before → After demo.

The generator never scans a real Desktop. By default it may only write below
the operating system's temporary directory. A project-local run is available
only with ``--force-project-demo`` and is confined to the dedicated hidden
``.froganize-demo-runtime`` directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from dropnest.models import EvaluationGroup
from dropnest.planner import build_desktop_assessment
from dropnest.workspace import initialize_workspace

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
PROJECT_DEMO_NAME: Final = ".froganize-demo-runtime"
DEFAULT_DEMO_NAME: Final = "froganize-demo"
MARKER_NAME: Final = ".froganize-demo"
MANIFEST_NAME: Final = "manifest.json"
MARKER_MAGIC: Final = "froganize-safe-demo-v1"
DEFAULT_PORT: Final = 8876
AGE_BOUNDARY_MARGIN: Final = timedelta(seconds=2)
EXPECTED_COUNTS: Final = {
    EvaluationGroup.RECENT: 2,
    EvaluationGroup.KEEP: 0,
    EvaluationGroup.ARCHIVE: 6,
    EvaluationGroup.CLEANUP: 2,
    EvaluationGroup.UNSAFE: 2,
}


class DemoSafetyError(ValueError):
    """Raised when a requested demo location is not safe."""


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Paths and verification details for one generated demo."""

    root: Path
    desktop: Path
    workspace: Path
    manifest: Path
    counts: dict[str, int]
    start_command: str
    browser_url: str


@dataclass(frozen=True, slots=True)
class DemoItem:
    """One synthetic top-level Desktop item."""

    name: str
    expected_group: EvaluationGroup
    kind: str
    age_days: int | None
    description: str
    child_name: str | None = None


DEMO_ITEMS: Final = (
    DemoItem(
        "Fresh Screenshot.png",
        EvaluationGroup.RECENT,
        "file",
        2,
        "A recently captured image.",
    ),
    DemoItem(
        "Active Design",
        EvaluationGroup.RECENT,
        "directory",
        5,
        "A current design folder kept as one whole item.",
        "wireframe.txt",
    ),
    DemoItem(
        "Draft Presentation.pptx",
        EvaluationGroup.ARCHIVE,
        "file",
        14,
        "An Office presentation inactive for more than one week.",
    ),
    DemoItem(
        "Reference Photos",
        EvaluationGroup.ARCHIVE,
        "directory",
        21,
        "A reference folder suggested for whole-folder archive.",
        "reference-photo.jpg",
    ),
    DemoItem(
        "report.pdf",
        EvaluationGroup.ARCHIVE,
        "file",
        45,
        "An old PDF with a pre-existing archive name conflict.",
    ),
    DemoItem(
        "Client Handoff",
        EvaluationGroup.ARCHIVE,
        "directory",
        75,
        "An old project folder archived without splitting its contents.",
        "handoff-notes.txt",
    ),
    DemoItem(
        "Meeting Recording.mp4",
        EvaluationGroup.ARCHIVE,
        "file",
        120,
        "An old synthetic video placeholder.",
    ),
    DemoItem(
        "Downloads 2025.zip",
        EvaluationGroup.ARCHIVE,
        "file",
        400,
        "An old download that demonstrates cross-year organization.",
    ),
    DemoItem(
        ".DS_Store",
        EvaluationGroup.CLEANUP,
        "file",
        None,
        "A reserved hidden file that is always skipped.",
    ),
    DemoItem(
        "~unfinished-download.tmp",
        EvaluationGroup.CLEANUP,
        "file",
        None,
        "A temporary download that is always skipped.",
    ),
    DemoItem(
        "Cloud Photo.jpg.icloud",
        EvaluationGroup.UNSAFE,
        "file",
        None,
        "A synthetic iCloud placeholder that is always skipped.",
    ),
    DemoItem(
        "External Shortcut",
        EvaluationGroup.UNSAFE,
        "symlink",
        None,
        "A dangling symbolic link that is never followed.",
    ),
)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_demo_root(
    target: str | os.PathLike[str] | None = None,
    *,
    force_project_demo: bool = False,
    project_root: Path = PROJECT_ROOT,
    temp_root: Path | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve and authorize one narrowly scoped demo root."""
    project = project_root.expanduser().resolve(strict=False)
    system_temp = (temp_root or Path(tempfile.gettempdir())).resolve(strict=False)
    protected_home = (home or Path.home()).expanduser().resolve(strict=False)
    protected_desktop = protected_home / "Desktop"
    project_demo = project / PROJECT_DEMO_NAME

    if target is None:
        raw = project_demo if force_project_demo else system_temp / DEFAULT_DEMO_NAME
    else:
        raw = Path(target).expanduser()
    if ".." in raw.parts:
        raise DemoSafetyError("Demo paths may not contain '..'.")

    absolute = Path(os.path.abspath(os.fspath(raw)))
    if absolute.is_symlink():
        raise DemoSafetyError("The demo root cannot be a symbolic link.")
    resolved = absolute.resolve(strict=False)
    filesystem_root = Path(resolved.anchor)

    if resolved in {filesystem_root, protected_home, protected_desktop, system_temp}:
        raise DemoSafetyError(
            "The filesystem root, home, Desktop, and temporary root are protected."
        )
    if _is_within(resolved, protected_desktop):
        raise DemoSafetyError("A real Desktop may never contain a generated demo.")

    allowed_in_temp = _is_within(resolved, system_temp)
    allowed_in_project = (
        force_project_demo
        and resolved != project
        and _is_within(resolved, project_demo)
    )
    if not (allowed_in_temp or allowed_in_project):
        raise DemoSafetyError(
            "Demo output must be below the system temporary directory. "
            f"Use --force-project-demo only for {project_demo}."
        )
    return resolved


def _marker_payload(root: Path) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "magic": MARKER_MAGIC,
        "root": str(root),
    }


def _validate_existing_demo(root: Path) -> None:
    marker = root / MARKER_NAME
    if marker.is_symlink() or not marker.is_file():
        raise DemoSafetyError(
            f"Refusing to reset an unmarked directory: {root}"
        )
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemoSafetyError(f"Demo safety marker is invalid: {marker}") from exc
    expected = _marker_payload(root)
    if payload != expected:
        raise DemoSafetyError(f"Demo safety marker does not match its root: {marker}")


def _prepare_root(root: Path, *, reset: bool) -> None:
    if root.is_symlink():
        raise DemoSafetyError("The demo root cannot be a symbolic link.")
    if root.exists():
        if not root.is_dir():
            raise DemoSafetyError(f"Demo output is not a directory: {root}")
        _validate_existing_demo(root)
        if not reset:
            raise DemoSafetyError(
                f"Demo already exists: {root}. Re-run with --reset to rebuild it."
            )
        shutil.rmtree(root)
    root.mkdir(parents=True)
    marker = root / MARKER_NAME
    marker.write_text(
        json.dumps(_marker_payload(root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_synthetic_file(path: Path, description: str) -> None:
    """Write a tiny, clearly labelled placeholder without copying user data."""
    path.write_text(
        "Froganize synthetic demo file\n"
        f"{description}\n"
        "This file contains no personal or downloaded content.\n",
        encoding="utf-8",
    )


def _set_age(path: Path, *, now: datetime, days: int) -> None:
    # Keep the item just beyond the whole-day boundary. Some filesystems and
    # timestamp conversions round sub-second values in opposite directions;
    # without this small margin, an intended 45-day item can display as 44.
    timestamp = (now - timedelta(days=days) - AGE_BOUNDARY_MARGIN).timestamp()
    os.utime(path, (timestamp, timestamp), follow_symlinks=False)


def _create_item(desktop: Path, root: Path, item: DemoItem, now: datetime) -> Path:
    path = desktop / item.name
    if item.kind == "directory":
        path.mkdir()
        assert item.child_name is not None
        child = path / item.child_name
        _write_synthetic_file(child, item.description)
        assert item.age_days is not None
        _set_age(child, now=now, days=item.age_days)
        _set_age(path, now=now, days=item.age_days)
        return path
    if item.kind == "symlink":
        # The target intentionally does not exist. The planner must classify the
        # link itself without resolving or reading anything outside the Desktop.
        path.symlink_to(root / "missing-synthetic-link-target.txt")
        return path

    _write_synthetic_file(path, item.description)
    if item.age_days is not None:
        _set_age(path, now=now, days=item.age_days)
    return path


def _build_start_command(workspace: Path, desktop: Path, port: int) -> str:
    local_executable = PROJECT_ROOT / ".venv" / "bin" / "dropnest"
    executable = str(local_executable) if local_executable.is_file() else "dropnest"
    return shlex.join(
        (
            executable,
            "web",
            str(workspace),
            "--desktop",
            str(desktop),
            "--port",
            str(port),
        )
    )


def create_demo(
    target: str | os.PathLike[str] | None = None,
    *,
    reset: bool = False,
    force_project_demo: bool = False,
    now: datetime | None = None,
    port: int = DEFAULT_PORT,
    project_root: Path = PROJECT_ROOT,
    temp_root: Path | None = None,
    home: Path | None = None,
) -> DemoResult:
    """Create and self-check a synthetic Desktop and Froganize workspace."""
    if not 1 <= port <= 65535:
        raise ValueError("Demo port must be between 1 and 65535.")
    reference_time = now or datetime.now().astimezone()
    if reference_time.tzinfo is None:
        raise ValueError("Demo time must include a timezone.")
    reference_time = reference_time.replace(microsecond=0)

    root = resolve_demo_root(
        target,
        force_project_demo=force_project_demo,
        project_root=project_root,
        temp_root=temp_root,
        home=home,
    )
    _prepare_root(root, reset=reset)

    desktop = root / "Desktop"
    desktop.mkdir()
    workspace = initialize_workspace(root / "Workspace").workspace
    created_paths = {
        item.name: _create_item(desktop, root, item, reference_time)
        for item in DEMO_ITEMS
    }

    report = created_paths["report.pdf"]
    report_time = datetime.fromtimestamp(
        report.stat(follow_symlinks=False).st_mtime
    ).astimezone()
    conflict_directory = (
        workspace.timeline
        / f"{report_time.year:04d}"
        / f"{report_time.year:04d}-{report_time.month:02d}"
    )
    conflict_directory.mkdir(parents=True)
    conflict = conflict_directory / "report.pdf"
    _write_synthetic_file(
        conflict,
        "An existing archive item used to demonstrate safe conflict renaming.",
    )

    assessment = build_desktop_assessment(
        workspace.root,
        desktop_path=desktop,
        now=reference_time,
    )
    counts = {
        group.value: assessment.count(group)
        for group in EvaluationGroup
    }
    expected = {
        group.value: count
        for group, count in EXPECTED_COUNTS.items()
    }
    if counts != expected:
        raise RuntimeError(
            f"Generated demo did not match expected groups: {counts!r}"
        )

    assessment_by_name = {
        entry.plan_entry.source.name: entry
        for entry in assessment.entries
    }
    report_entry = assessment_by_name["report.pdf"].plan_entry
    if report_entry.target is None or report_entry.target.name != "report (1).pdf":
        raise RuntimeError("Generated demo did not create the expected name conflict.")

    start_command = _build_start_command(workspace.root, desktop, port)
    manifest_path = root / MANIFEST_NAME
    manifest = {
        "schema_version": 1,
        "generated_at": reference_time.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "synthetic_only": True,
        "desktop": str(desktop),
        "workspace": str(workspace.root),
        "timeline": str(workspace.timeline),
        "expected_counts": expected,
        "preexisting_conflict": str(conflict),
        "expected_conflict_target": str(report_entry.target),
        "start_command": start_command,
        "browser_url": f"http://127.0.0.1:{port}",
        "items": [
            {
                "name": item.name,
                "kind": item.kind,
                "age_days": item.age_days,
                "expected_group": item.expected_group.value,
                "description": item.description,
            }
            for item in DEMO_ITEMS
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return DemoResult(
        root=root,
        desktop=desktop,
        workspace=workspace.root,
        manifest=manifest_path,
        counts=counts,
        start_command=start_command,
        browser_url=f"http://127.0.0.1:{port}",
    )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "time must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("time must include a timezone")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a safe, synthetic Froganize Before → After demo.",
        epilog="No service is started and no real Desktop is scanned.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="demo root (default: a dedicated system temporary directory)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="rebuild an existing directory bearing a valid demo marker",
    )
    parser.add_argument(
        "--force-project-demo",
        action="store_true",
        help=(
            "allow the dedicated project-local "
            f"{PROJECT_DEMO_NAME} directory"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port shown in the safe launch command (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--now",
        type=_parse_time,
        help="fixed ISO-8601 reference time for reproducible screenshots",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = create_demo(
            arguments.target,
            reset=arguments.reset,
            force_project_demo=arguments.force_project_demo,
            now=arguments.now,
            port=arguments.port,
        )
    except (DemoSafetyError, OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("Froganize demo ready.")
    print(f"Demo root: {result.root}")
    print(f"Before (synthetic Desktop): {result.desktop}")
    print(f"After (monthly Timeline): {result.workspace / 'Timeline'}")
    print(
        "Groups: "
        f"recent={result.counts['recent']}, "
        f"keep={result.counts['keep']}, "
        f"archive={result.counts['archive']}, "
        f"cleanup={result.counts['cleanup']}, "
        f"unsafe={result.counts['unsafe']}"
    )
    print(f"Manifest: {result.manifest}")
    print("\nSafe launch command (not executed):")
    print(result.start_command)
    print(f"Then open: {result.browser_url}")
    print("\nTo rebuild the same synthetic demo, add --reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
