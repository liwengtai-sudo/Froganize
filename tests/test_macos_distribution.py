"""Checks that the macOS distribution stays self-contained and branded."""

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "scripts/build_macos_distribution.sh"


def test_frozen_entry_uses_the_self_contained_application() -> None:
    source = (PROJECT_ROOT / "scripts" / "froganize_app_entry.py").read_text(
        encoding="utf-8"
    )

    assert "from dropnest.macos_app import main" in source
    assert ".venv" not in source
    assert "/Users/" not in source


def test_pyinstaller_spec_bundles_assets_and_froganize_identity() -> None:
    source = (PROJECT_ROOT / "packaging" / "Froganize.spec").read_text(
        encoding="utf-8"
    )

    assert 'collect_data_files("dropnest")' in source
    assert "runtime_collections_abc.py" in source
    assert 'name="Froganize.app"' in source
    assert 'bundle_identifier="app.froganize.Froganize"' in source
    assert 'os.environ.get("FROGANIZE_CODESIGN_IDENTITY")' in source
    assert "codesign_identity=CODESIGN_IDENTITY" in source
    assert "Froganize.icns" in source
    assert "NSDesktopFolderUsageDescription" in source
    assert "NSDocumentsFolderUsageDescription" in source
    assert "/Users/" not in source


def test_build_script_marks_local_candidate_as_unnotarized() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'RELEASE_KIND="unsigned"' in source
    assert "Froganize-${VERSION}-macos-${ARCH}-${RELEASE_KIND}.dmg" in source
    assert "not notarized" in source
    assert "codesign --verify" in source
    assert "FROGANIZE_SKIP_DMG" in source
    assert 'FROGANIZE_DMG_TARGET:-applications' in source
    assert '"${STAGING_DIR}/Desktop"' in source
    assert "local-machine candidate" in source
    assert "signed-unnotarized" in source
    assert "local-signed" in source
    assert "FROGANIZE_LOCAL_CODESIGN_IDENTITY" in source
    assert "--timestamp=none" in source
    assert "anchor = H\"" in source
    assert '"${LOCAL_REQUIREMENT}" == *cdhash*' in source
    assert 'identifier \"app.froganize.Froganize\"' in source
    assert "a local signing identity cannot be used for notarization" in source
    assert "Developer ID releases must use the Applications target" in source
    assert 'notarytool submit "${DMG_PATH}"' in source
    assert 'stapler staple "${DMG_PATH}"' in source
    assert "context:primary-signature" in source
    assert 'PYINSTALLER_CONFIG_DIR="${BUILD_ROOT}/pyinstaller-config"' in source
    assert "import PySide6" in source
    assert ".[packaging]" in source
    assert "smoke_macos_bundle.py" in source
    assert "/Users/" not in source


def test_distribution_rejects_local_identity_for_notarization() -> None:
    environment = os.environ.copy()
    environment.pop("FROGANIZE_CODESIGN_IDENTITY", None)
    environment["FROGANIZE_LOCAL_CODESIGN_IDENTITY"] = "local-test"
    environment["FROGANIZE_NOTARY_PROFILE"] = "notary-test"
    result = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "local signing identity cannot be used for notarization" in result.stderr


def test_source_distribution_includes_macos_build_inputs() -> None:
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "scripts/build_macos_distribution.sh" in manifest
    assert "scripts/froganize_app_entry.py" in manifest
    assert "scripts/smoke_macos_bundle.py" in manifest
    assert "recursive-include packaging *.py *.spec" in manifest


def test_bundle_smoke_checks_a_gui_window_without_starting_a_web_service() -> None:
    source = (PROJECT_ROOT / "scripts" / "smoke_macos_bundle.py").read_text(
        encoding="utf-8"
    )

    assert "FROGANIZE_SMOKE_READY_FILE" in source
    assert '"QT_QPA_PLATFORM": "offscreen"' in source
    assert 'state / "server.json"' in source
    assert "api/health" not in source
    assert "urllib.request" not in source
