"""Static and isolated behavior checks for the local macOS launcher."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def test_froganize_app_icon_is_a_well_formed_icns_resource() -> None:
    icon = PROJECT_ROOT / "assets" / "Froganize.icns"
    data = icon.read_bytes()

    assert data[:4] == b"icns"
    assert int.from_bytes(data[4:8], byteorder="big") == len(data)


def test_launcher_installer_uses_the_froganize_icon() -> None:
    installer = (SCRIPTS / "install_macos_launcher.sh").read_text(
        encoding="utf-8"
    )

    assert 'ICON_PATH="${PROJECT_DIR}/assets/Froganize.icns"' in installer
    assert 'ICON_RESOURCE_NAME="Froganize.icns"' in installer
    assert 'DESKTOP_SHORTCUT="${HOME}/Desktop/Froganize.app"' in installer
    assert 'BUNDLE_IDENTIFIER="org.froganize.DropNest"' in installer
    assert "CFBundleShortVersionString" in installer


def test_launcher_sources_do_not_contain_a_personal_absolute_path() -> None:
    for name in (
        "DropNestLauncher.applescript",
        "install_macos_launcher.sh",
        "launch_dropnest_web.sh",
    ):
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "/Users/" not in source
        assert "liwengtai" not in source


def test_applescript_loads_bound_paths_from_app_resources() -> None:
    source = (SCRIPTS / "DropNestLauncher.applescript").read_text(
        encoding="utf-8"
    )

    assert '(POSIX path of (path to me)) & "Contents/Resources/"' in source
    assert 'resourceRoot & "launch_dropnest_web.sh"' in source
    assert 'resourceRoot & "launcher.conf"' in source
    assert "(quoted form of workspacePath)" in source
    assert "(quoted form of projectRoot)" in source


def test_runtime_launcher_requires_an_explicit_workspace() -> None:
    result = subprocess.run(
        [str(SCRIPTS / "launch_dropnest_web.sh")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_runtime_verifies_healthy_server_workspace_before_process_fallback() -> None:
    source = (SCRIPTS / "launch_dropnest_web.sh").read_text(encoding="utf-8")

    health_check = source.index("if server_ready; then")
    workspace_check = source.index(
        "if server_matches_workspace; then",
        health_check,
    )
    binding_check = source.index(
        'if ! server_matches_binding "${LISTENER_PID}"; then',
        workspace_check,
    )
    assert health_check < workspace_check < binding_check
    assert '"${STATUS_URL}"' in source
    assert "different workspace" in source


def _macos_launcher_tools_available() -> bool:
    return platform.system() == "Darwin" and all(
        Path(tool).exists()
        for tool in (
            "/usr/bin/codesign",
            "/usr/bin/osacompile",
        )
    )


def _prepare_fake_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "Checkout With Spaces"
    scripts = checkout / "scripts"
    assets = checkout / "assets"
    executable = checkout / ".venv" / "bin" / "dropnest"
    scripts.mkdir(parents=True)
    assets.mkdir()
    executable.parent.mkdir(parents=True)

    for name in (
        "DropNestLauncher.applescript",
        "install_macos_launcher.sh",
        "launch_dropnest_web.sh",
    ):
        shutil.copy2(SCRIPTS / name, scripts / name)
    shutil.copy2(
        PROJECT_ROOT / "assets" / "Froganize.icns",
        assets / "Froganize.icns",
    )
    executable.write_text(
        """#!/bin/zsh
set -eu
command="$1"
workspace="$2"
if [[ "${command}" == "init" ]]; then
  /bin/mkdir -p \
    "${workspace}/Inbox" \
    "${workspace}/Timeline" \
    "${workspace}/.dropnest"
  /usr/bin/printf '{}\\n' >"${workspace}/.dropnest/config.json"
  : >"${workspace}/.dropnest/history.jsonl"
elif [[ "${command}" == "status" ]]; then
  [[ -d "${workspace}/Inbox" ]]
  [[ -d "${workspace}/Timeline" ]]
  [[ -f "${workspace}/.dropnest/config.json" ]]
  [[ -f "${workspace}/.dropnest/history.jsonl" ]]
else
  exit 64
fi
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return checkout


@pytest.mark.skipif(
    not _macos_launcher_tools_available(),
    reason="the launcher bundle is built only on macOS",
)
def test_installer_binds_checkout_and_existing_legacy_workspace(
    tmp_path: Path,
) -> None:
    checkout = _prepare_fake_checkout(tmp_path)
    home = tmp_path / "Home"
    legacy_workspace = home / "Documents" / "DropNestWorkspace"
    desktop_item = home / "Desktop" / "Froganize.app"
    legacy_workspace.mkdir(parents=True)
    desktop_item.parent.mkdir(parents=True)
    desktop_item.write_text("keep me", encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        [str(checkout / "scripts" / "install_macos_launcher.sh")],
        cwd=checkout,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert desktop_item.read_text(encoding="utf-8") == "keep me"
    assert "Existing Desktop item was not replaced" in result.stdout
    assert (legacy_workspace / ".dropnest" / "history.jsonl").is_file()

    app = home / "Applications" / "DropNest.app"
    config = app / "Contents" / "Resources" / "launcher.conf"
    assert config.read_text(encoding="utf-8").splitlines() == [
        str(checkout.resolve()),
        str(legacy_workspace.resolve()),
    ]
    assert (
        app / "Contents" / "Resources" / "launch_dropnest_web.sh"
    ).is_file()
    plist = subprocess.run(
        ["/usr/bin/plutil", "-p", str(app / "Contents" / "Info.plist")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert '"CFBundleIdentifier" => "org.froganize.DropNest"' in plist
    assert '"CFBundleShortVersionString" => "0.3.0"' in plist
    assert '"CFBundleIconFile" => "Froganize.icns"' in plist
    assert (
        app / "Contents" / "Resources" / "Froganize.icns"
    ).is_file()


@pytest.mark.skipif(
    not _macos_launcher_tools_available(),
    reason="the launcher bundle is built only on macOS",
)
def test_installer_accepts_an_explicit_workspace(tmp_path: Path) -> None:
    checkout = _prepare_fake_checkout(tmp_path)
    home = tmp_path / "Home"
    workspace = tmp_path / "Custom Workspace"
    old_app = home / "Applications" / "DropNest.app"
    legacy_shortcut = home / "Desktop" / "DropNest.app"
    legacy_shortcut.parent.mkdir(parents=True)
    legacy_shortcut.symlink_to(old_app)
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        [
            str(checkout / "scripts" / "install_macos_launcher.sh"),
            str(workspace),
        ],
        cwd=checkout,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    config = (
        home
        / "Applications"
        / "DropNest.app"
        / "Contents"
        / "Resources"
        / "launcher.conf"
    )
    assert config.read_text(encoding="utf-8").splitlines() == [
        str(checkout.resolve()),
        str(workspace.resolve()),
    ]
    assert (workspace / "Inbox").is_dir()
    assert (home / "Desktop" / "Froganize.app").is_symlink()
    assert not legacy_shortcut.exists()
    assert not legacy_shortcut.is_symlink()
    assert "Legacy Desktop shortcut removed" in result.stdout


@pytest.mark.skipif(
    not _macos_launcher_tools_available(),
    reason="the launcher bundle is built only on macOS",
)
def test_installer_defaults_to_froganize_workspace_when_legacy_is_absent(
    tmp_path: Path,
) -> None:
    checkout = _prepare_fake_checkout(tmp_path)
    home = tmp_path / "Home"
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        [str(checkout / "scripts" / "install_macos_launcher.sh")],
        cwd=checkout,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    workspace = home / "Documents" / "FroganizeWorkspace"
    config = (
        home
        / "Applications"
        / "DropNest.app"
        / "Contents"
        / "Resources"
        / "launcher.conf"
    )
    assert config.read_text(encoding="utf-8").splitlines() == [
        str(checkout.resolve()),
        str(workspace.resolve()),
    ]
    assert (workspace / "Inbox").is_dir()
