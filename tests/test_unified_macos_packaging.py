"""Static and disposable-path checks for the unified macOS prototype."""

from __future__ import annotations

import importlib.util
import os
import plistlib
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "scripts/build_unified_macos_prototype.sh"
SMOKE_SCRIPT = PROJECT_ROOT / "scripts/smoke_unified_macos_bundle.py"
LOCAL_IDENTITY_SCRIPT = (
    PROJECT_ROOT / "scripts/create_local_codesign_identity.sh"
)
LOCAL_STABILITY_SCRIPT = (
    PROJECT_ROOT / "scripts/verify_local_codesign_stability.sh"
)
AGENT_BUILD_SCRIPT = (
    PROJECT_ROOT / "swift/ScreenshotIntelligence/Scripts/build-app.sh"
)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("unified_bundle_smoke", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_plist(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        plistlib.dump(values, stream)


def _write_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def _fake_unified_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "Froganize.app"
    _write_plist(
        bundle / "Contents/Info.plist",
        {
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "Froganize",
            "CFBundleIdentifier": "app.froganize.Froganize",
            "CFBundleShortVersionString": "0.3.0",
        },
    )
    _write_executable(bundle / "Contents/MacOS/Froganize")
    _write_executable(bundle / "Contents/MacOS/FroganizeFileOps")

    agent = (
        bundle
        / "Contents/Library/LoginItems/FroganizeScreenshotAgent.app"
    )
    _write_plist(
        agent / "Contents/Info.plist",
        {
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "ScreenshotRenamer",
            "CFBundleIdentifier": (
                "app.froganize.Froganize.ScreenshotIntelligence"
            ),
            "CFBundleDisplayName": "Froganize Screenshot Intelligence",
            "CFBundleShortVersionString": "0.3.0",
            "LSUIElement": True,
            "NSDesktopFolderUsageDescription": (
                "Only process matching system screenshots in the selected Desktop folder."
            ),
            "NSDocumentsFolderUsageDescription": (
                "Only process matching system screenshots in the selected Documents folder."
            ),
            "NSDownloadsFolderUsageDescription": (
                "Only process matching system screenshots in the selected Downloads folder."
            ),
        },
    )
    _write_executable(agent / "Contents/MacOS/ScreenshotRenamer")
    return bundle


def test_unified_bundle_smoke_accepts_the_fixed_layout(tmp_path: Path) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)

    module.validate_bundle(bundle)

    assert module.FILEOPS_EXECUTABLE == Path("Contents/MacOS/FroganizeFileOps")
    assert module.SCREENSHOT_AGENT == Path(
        "Contents/Library/LoginItems/FroganizeScreenshotAgent.app"
    )
    assert module.SCREENSHOT_CONTROL_EXECUTABLE == Path(
        "Contents/Library/LoginItems/FroganizeScreenshotAgent.app/Contents/"
        "MacOS/ScreenshotRenamer"
    )
    assert module.BUNDLE_EXECUTION_ROLES == (
        Path("Contents/MacOS/Froganize"),
        Path("Contents/MacOS/FroganizeFileOps"),
        module.SCREENSHOT_CONTROL_EXECUTABLE,
    )
    agent_plist = plistlib.loads(
        (bundle / module.SCREENSHOT_AGENT / "Contents/Info.plist").read_bytes()
    )
    assert all(
        agent_plist[key]
        for key in module.AGENT_FOLDER_USAGE_DESCRIPTION_KEYS
    )


@pytest.mark.parametrize(
    "missing_key",
    [
        "NSDesktopFolderUsageDescription",
        "NSDocumentsFolderUsageDescription",
        "NSDownloadsFolderUsageDescription",
    ],
)
def test_unified_bundle_smoke_requires_nested_agent_folder_privacy_descriptions(
    tmp_path: Path,
    missing_key: str,
) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    agent_plist = bundle / module.SCREENSHOT_AGENT / "Contents/Info.plist"
    values = plistlib.loads(agent_plist.read_bytes())
    values.pop(missing_key)
    _write_plist(agent_plist, values)

    with pytest.raises(
        module.BundleValidationError,
        match="folder privacy description",
    ):
        module.validate_bundle(bundle)


def test_unified_bundle_smoke_fails_closed_when_helper_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    (bundle / module.FILEOPS_EXECUTABLE).unlink()

    with pytest.raises(module.BundleValidationError, match="file-operation helper"):
        module.validate_bundle(bundle)


def test_unified_bundle_smoke_rejects_a_symlinked_helper(tmp_path: Path) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    helper = bundle / module.FILEOPS_EXECUTABLE
    external = tmp_path / "external-helper"
    _write_executable(external)
    helper.unlink()
    helper.symlink_to(external)

    with pytest.raises(module.BundleValidationError, match="symbolic link"):
        module.validate_bundle(bundle)


def test_unified_bundle_smoke_rejects_an_agent_parent_escape(
    tmp_path: Path,
) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    login_items = bundle / "Contents/Library/LoginItems"
    external = tmp_path / "external-login-items"
    login_items.rename(external)
    login_items.symlink_to(external, target_is_directory=True)

    with pytest.raises(module.BundleValidationError, match="resolves outside"):
        module.validate_bundle(bundle)


def test_unified_bundle_smoke_rejects_mismatched_component_versions(
    tmp_path: Path,
) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    agent_plist = bundle / module.SCREENSHOT_AGENT / "Contents/Info.plist"
    values = plistlib.loads(agent_plist.read_bytes())
    values["CFBundleShortVersionString"] = "0.1.0"
    _write_plist(agent_plist, values)

    with pytest.raises(module.BundleValidationError, match="versions do not match"):
        module.validate_bundle(bundle)


def test_unified_bundle_smoke_rejects_a_different_control_entry(
    tmp_path: Path,
) -> None:
    module = _load_smoke_module()
    bundle = _fake_unified_bundle(tmp_path)
    agent_plist = bundle / module.SCREENSHOT_AGENT / "Contents/Info.plist"
    values = plistlib.loads(agent_plist.read_bytes())
    values["CFBundleExecutable"] = "AnotherExecutable"
    _write_plist(agent_plist, values)

    with pytest.raises(
        module.BundleValidationError,
        match="agent/control executable name is unexpected",
    ):
        module.validate_bundle(bundle)


def test_unified_build_script_uses_one_bundle_and_signs_inside_out() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '${PROJECT_ROOT}/swift/ScreenshotIntelligence' in source
    assert "FROGANIZE_AGENT_PROJECT" in source
    assert '--onefile' in source
    assert '--console' in source
    assert '--name FroganizeFileOps' in source
    assert 'OUTPUT_APP="${OUTPUT_ROOT}/Froganize.app"' in source
    assert (
        'HELPER_DESTINATION="${OUTPUT_APP}/Contents/MacOS/FroganizeFileOps"'
        in source
    )
    assert (
        'NESTED_AGENT="${OUTPUT_APP}/Contents/Library/LoginItems/'
        'FroganizeScreenshotAgent.app"' in source
    )
    assert "Froganize Screenshot Intelligence.app" in source
    assert "FroganizeScreenshotAgent.app" in source
    assert source.count(
        '-c "Set :CFBundleShortVersionString ${UNIFIED_VERSION}"'
    ) == 2
    assert source.index('sign_executable "${HELPER_DESTINATION}"') < source.index(
        'sign_bundle "${NESTED_AGENT}"'
    ) < source.index('sign_bundle "${OUTPUT_APP}"')
    assert "smoke_unified_macos_bundle.py" in source


def test_unified_build_supports_an_explicit_stable_local_identity() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "FROGANIZE_LOCAL_CODESIGN_IDENTITY" in source
    assert "set only one of FROGANIZE_CODESIGN_IDENTITY" in source
    assert "--timestamp=none" in source
    assert "anchor = H\"" in source
    assert '"${requirement}" == *cdhash*' in source
    assert 'identifier \\"${expected_identifier}\\"' in source
    assert "app.froganize.Froganize.ScreenshotIntelligence" in source
    assert '"app.froganize.Froganize"' in source
    assert "verify_agent_identifier" in source
    assert 'verify_local_requirement \\\n    "${NESTED_AGENT}" \\\n' in source
    assert 'verify_local_requirement \\\n    "${OUTPUT_APP}" \\\n' in source
    assert "not Developer ID" in source


def test_unified_build_rejects_conflicting_signing_modes() -> None:
    environment = os.environ.copy()
    environment["FROGANIZE_CODESIGN_IDENTITY"] = "developer-test"
    environment["FROGANIZE_LOCAL_CODESIGN_IDENTITY"] = "local-test"
    result = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "set only one" in result.stderr


def test_swift_agent_build_uses_the_same_explicit_signing_modes() -> None:
    source = AGENT_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "FROGANIZE_LOCAL_CODESIGN_IDENTITY" in source
    assert "FROGANIZE_CODESIGN_IDENTITY" in source
    assert "--timestamp=none" in source
    assert "anchor = H\"" in source
    assert "codesign --verify --deep --strict" in source
    assert (
        'identifier \"app.froganize.Froganize.ScreenshotIntelligence\"'
        in source
    )


def test_local_identity_creation_is_explicit_and_least_privilege() -> None:
    source = LOCAL_IDENTITY_SCRIPT.read_text(encoding="utf-8")

    assert "extendedKeyUsage = 1.3.6.1.5.5.7.3.3" in source
    assert "keyUsage = critical, digitalSignature" in source
    assert "/usr/bin/security add-trusted-cert" in source
    assert "-p codeSign" in source
    assert "-T /usr/bin/codesign" in source
    assert "-x" in source
    assert "-t priv" not in source
    assert "-f openssl" not in source
    assert "find-identity -v -p codesigning" in source
    assert "-P " not in source
    assert "\n+  -A" not in source
    assert "\n  -d \\n" not in source
    assert "delete-identity" in source
    assert "delete-certificate" in source
    assert "CREATED_FINGERPRINT" in source
    assert "Type CREATE" in source
    assert "sudo " not in source
    assert LOCAL_IDENTITY_SCRIPT.name not in BUILD_SCRIPT.read_text(
        encoding="utf-8"
    )


def test_local_identity_help_does_not_modify_a_keychain() -> None:
    result = subprocess.run(
        [str(LOCAL_IDENTITY_SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "changes the selected macOS keychain" in result.stdout
    assert "must not be published" in result.stdout


def test_local_stability_check_is_read_only_and_compares_requirements() -> None:
    source = LOCAL_STABILITY_SCRIPT.read_text(encoding="utf-8")

    assert "app.froganize.Froganize.ScreenshotIntelligence" in source
    assert "Signature=adhoc" in source
    assert "anchor = H\"" in source
    assert "cdhash" in source
    assert 'identifier \\"${EXPECTED_BUNDLE_ID}\\"' in source
    assert '"${OLD_REQUIREMENT}" != "${NEW_REQUIREMENT}"' in source
    assert "security " not in source
    assert "delete" not in source
    assert "--force" not in source


def test_unified_build_fails_before_building_for_a_missing_agent(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["FROGANIZE_AGENT_PROJECT"] = str(tmp_path / "missing-agent")
    result = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Screenshot Intelligence project is missing" in result.stderr
    assert "Running PyInstaller" not in result.stdout


def test_unified_packaging_sources_have_no_personal_absolute_paths() -> None:
    for path in (
        BUILD_SCRIPT,
        SMOKE_SCRIPT,
        PROJECT_ROOT / "scripts/froganize_fileops_entry.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "/Users/" not in source
        assert "liwengtai" not in source


def test_unified_smoke_never_launches_the_main_app_or_agent() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "Popen" not in source
    assert "open(" not in source.replace("path.open(", "")
    assert "SCREENSHOT_CONTROL_EXECUTABLE" in source


def test_fileops_frozen_entry_delegates_without_local_filesystem_logic() -> None:
    source = (PROJECT_ROOT / "scripts/froganize_fileops_entry.py").read_text(
        encoding="utf-8"
    )

    assert "from dropnest.agent_cli import main" in source
    assert "shutil" not in source
    assert "FileManager" not in source


def test_source_distribution_includes_unified_packaging_inputs() -> None:
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "scripts/build_unified_macos_prototype.sh" in manifest
    assert "scripts/create_local_codesign_identity.sh" in manifest
    assert "scripts/verify_local_codesign_stability.sh" in manifest
    assert "scripts/froganize_fileops_entry.py" in manifest
    assert "scripts/smoke_unified_macos_bundle.py" in manifest
    assert "swift/ScreenshotIntelligence/Package.swift" in manifest
    assert "swift/ScreenshotIntelligence/Sources" in manifest
