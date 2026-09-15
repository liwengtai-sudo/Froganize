"""Validate a unified Froganize bundle without launching either application."""

from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path


MAIN_EXECUTABLE = Path("Contents/MacOS/Froganize")
FILEOPS_EXECUTABLE = Path("Contents/MacOS/FroganizeFileOps")
SCREENSHOT_AGENT = Path(
    "Contents/Library/LoginItems/FroganizeScreenshotAgent.app"
)
SCREENSHOT_CONTROL_EXECUTABLE = (
    SCREENSHOT_AGENT / "Contents/MacOS/ScreenshotRenamer"
)
BUNDLE_EXECUTION_ROLES = (
    MAIN_EXECUTABLE,
    FILEOPS_EXECUTABLE,
    SCREENSHOT_CONTROL_EXECUTABLE,
)
OUTER_BUNDLE_IDENTIFIER = "app.froganize.Froganize"
AGENT_BUNDLE_IDENTIFIER = "app.froganize.Froganize.ScreenshotIntelligence"
AGENT_DISPLAY_NAME = "Froganize Screenshot Intelligence"
AGENT_FOLDER_USAGE_DESCRIPTION_KEYS = (
    "NSDesktopFolderUsageDescription",
    "NSDocumentsFolderUsageDescription",
    "NSDownloadsFolderUsageDescription",
)


class BundleValidationError(RuntimeError):
    """The unified application bundle is incomplete or unsafe to ship."""


def _require_real_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise BundleValidationError(f"{label} must not be a symbolic link: {path}")
    if not path.is_dir():
        raise BundleValidationError(f"Missing {label}: {path}")


def _require_executable(path: Path, label: str) -> None:
    if path.is_symlink():
        raise BundleValidationError(f"{label} must not be a symbolic link: {path}")
    if not path.is_file():
        raise BundleValidationError(f"Missing {label}: {path}")
    if not os.access(path, os.X_OK):
        raise BundleValidationError(f"{label} is not executable: {path}")


def _require_contained(root: Path, path: Path, label: str) -> None:
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BundleValidationError(
            f"{label} resolves outside the application bundle: {path}"
        ) from exc


def _load_plist(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise BundleValidationError(f"Missing {label}: {path}")
    try:
        with path.open("rb") as stream:
            value = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise BundleValidationError(f"Invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise BundleValidationError(f"Invalid {label}: {path}")
    return value


def validate_bundle(bundle: Path) -> None:
    """Check the fixed 0.3 prototype layout without starting a watcher."""
    bundle = bundle.expanduser()
    _require_real_directory(bundle, "Froganize application bundle")
    bundle_root = bundle.resolve(strict=True)

    outer_plist_path = bundle / "Contents/Info.plist"
    outer_plist = _load_plist(outer_plist_path, "outer Info.plist")
    _require_contained(bundle_root, outer_plist_path, "outer Info.plist")
    if outer_plist.get("CFBundlePackageType") != "APPL":
        raise BundleValidationError("The outer bundle is not a macOS application.")
    if outer_plist.get("CFBundleIdentifier") != OUTER_BUNDLE_IDENTIFIER:
        raise BundleValidationError("The outer bundle identifier is unexpected.")
    outer_version = outer_plist.get("CFBundleShortVersionString")
    if not isinstance(outer_version, str) or not outer_version:
        raise BundleValidationError("The outer bundle version is missing.")

    main_executable = bundle / MAIN_EXECUTABLE
    helper_executable = bundle / FILEOPS_EXECUTABLE
    _require_executable(main_executable, "main executable")
    _require_executable(helper_executable, "file-operation helper")
    _require_contained(bundle_root, main_executable, "main executable")
    _require_contained(bundle_root, helper_executable, "file-operation helper")

    agent = bundle / SCREENSHOT_AGENT
    _require_real_directory(agent, "nested screenshot agent")
    _require_contained(bundle_root, agent, "nested screenshot agent")
    agent_plist_path = agent / "Contents/Info.plist"
    agent_plist = _load_plist(agent_plist_path, "agent Info.plist")
    _require_contained(bundle_root, agent_plist_path, "agent Info.plist")
    if agent_plist.get("CFBundlePackageType") != "APPL":
        raise BundleValidationError("The screenshot agent is not an application bundle.")
    if agent_plist.get("LSUIElement") not in (True, 1):
        raise BundleValidationError("The screenshot agent must be a menu-bar agent.")
    if agent_plist.get("CFBundleIdentifier") != AGENT_BUNDLE_IDENTIFIER:
        raise BundleValidationError("The screenshot agent bundle identifier is unexpected.")
    if agent_plist.get("CFBundleDisplayName") != AGENT_DISPLAY_NAME:
        raise BundleValidationError("The screenshot agent display name is unexpected.")
    for key in AGENT_FOLDER_USAGE_DESCRIPTION_KEYS:
        description = agent_plist.get(key)
        if not isinstance(description, str) or not description.strip():
            raise BundleValidationError(
                f"The screenshot agent is missing a folder privacy description: {key}."
            )
    if agent_plist.get("CFBundleShortVersionString") != outer_version:
        raise BundleValidationError(
            "The outer app and screenshot agent versions do not match."
        )

    expected_agent_executable = SCREENSHOT_CONTROL_EXECUTABLE.name
    if agent_plist.get("CFBundleExecutable") != expected_agent_executable:
        raise BundleValidationError(
            "The screenshot agent/control executable name is unexpected."
        )
    agent_binary = bundle / SCREENSHOT_CONTROL_EXECUTABLE
    _require_executable(agent_binary, "screenshot agent/control executable")
    _require_contained(
        bundle_root, agent_binary, "screenshot agent/control executable"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        validate_bundle(args.bundle)
    except BundleValidationError as exc:
        parser.exit(1, f"Unified bundle validation failed: {exc}\n")
    print("Unified Froganize bundle structure passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
