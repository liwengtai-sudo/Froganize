"""Safety and integration tests for the Python Screenshot Intelligence helper."""

from __future__ import annotations

import json
import errno
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

import dropnest.screenshot_operations as operations
from dropnest.agent_cli import handle_payload
from dropnest.intelligence_contract import (
    RenameScreenshotRequest,
    parse_request_bytes,
    request_fingerprint,
)
from dropnest.intelligence_history import (
    EVENT_RENAME,
    EVENT_UNDO,
    IntelligencePaths,
    IntelligenceStorageError,
    default_paths,
    new_rename_record,
    read_activity,
)
from dropnest.intelligence_status import get_intelligence_status
from dropnest.screenshot_operations import execute_request, recover_pending_operations

FIXED_NOW = datetime(2026, 8, 12, 10, 20, 30).astimezone()


def request_id() -> str:
    return str(uuid.uuid4())


def payload(data: dict[str, object]) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def configure_payload(root: Path, *, identifier: str | None = None) -> bytes:
    return payload(
        {
            "schema_version": 1,
            "request_id": identifier or request_id(),
            "action": "configure_screenshot_root",
            "source_root": str(root),
        }
    )


def snapshot(path: Path) -> dict[str, int]:
    metadata = path.stat(follow_symlinks=False)
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": metadata.st_mode,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
    }


def rename_payload(
    source: Path,
    *,
    identifier: str | None = None,
    title: str = "GitHub 项目 README 修改建议",
    summary: str = "页面展示 README 修改建议。",
    category: str = "网页",
    confidence: float = 0.94,
    sensitive: bool = False,
    extra: dict[str, object] | None = None,
) -> bytes:
    data: dict[str, object] = {
        "schema_version": 1,
        "request_id": identifier or request_id(),
        "action": "rename_screenshot",
        "source_name": source.name,
        "snapshot": snapshot(source),
        "analysis": {
            "title": title,
            "summary": summary,
            "category": category,
            "confidence": confidence,
            "sensitive": sensitive,
        },
        "provider": "openrouter",
        "model": "test/vision-model",
    }
    if extra:
        data.update(extra)
    return payload(data)


def undo_payload(*, identifier: str | None = None, event_id: str | None = None) -> bytes:
    data: dict[str, object] = {
        "schema_version": 1,
        "request_id": identifier or request_id(),
        "action": "undo_screenshot_rename",
    }
    if event_id is not None:
        data["event_id"] = event_id
    return payload(data)


def execute_bytes(
    data: bytes,
    paths: IntelligencePaths,
    *,
    now: datetime = FIXED_NOW,
) -> dict[str, object]:
    return execute_request(parse_request_bytes(data), paths, now=now)


@pytest.fixture
def intelligence(tmp_path: Path) -> tuple[IntelligencePaths, Path]:
    paths = IntelligencePaths.from_root(tmp_path / "state")
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    response = execute_bytes(configure_payload(screenshots), paths)
    assert response["status"] == "configured"
    return paths, screenshots


@pytest.mark.parametrize(
    ("raw", "code"),
    (
        (b"not-json", "invalid_json"),
        (b"\xff", "invalid_utf8"),
        (payload({"schema_version": 99, "request_id": request_id(), "action": "x"}), "unsupported_schema"),
        (payload({"schema_version": 1, "request_id": "bad", "action": "x"}), "invalid_id"),
        (payload({"schema_version": 1, "request_id": request_id(), "action": "x"}), "unknown_action"),
    ),
)
def test_contract_errors_are_stable_json(raw: bytes, code: str, tmp_path: Path) -> None:
    response = handle_payload(raw, paths=IntelligencePaths.from_root(tmp_path / "state"))

    assert response["status"] == "error"
    assert response["error"]["code"] == code


def test_real_stdin_stdout_helper_emits_one_json_response(tmp_path: Path) -> None:
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    environment = os.environ.copy()
    environment["FROGANIZE_STATE_DIR"] = str(tmp_path / "state")

    completed = subprocess.run(
        [sys.executable, "-m", "dropnest.agent_cli"],
        input=configure_payload(screenshots),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    lines = completed.stdout.decode("utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "configured"


def test_console_helper_rejects_arguments_without_reading_stdin() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "dropnest.agent_cli", "--unsafe"],
        input=b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    response = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert completed.stderr == b""
    assert response["error"]["code"] == "unexpected_argument"


def test_contract_rejects_duplicate_and_unknown_fields(tmp_path: Path) -> None:
    identifier = request_id()
    duplicate = (
        '{"schema_version":1,"request_id":"'
        + identifier
        + '","action":"configure_screenshot_root","source_root":"/tmp/a",'
        + '"source_root":"/tmp/b"}'
    ).encode()

    duplicate_response = handle_payload(
        duplicate, paths=IntelligencePaths.from_root(tmp_path / "state")
    )
    unknown_response = handle_payload(
        payload(
            {
                "schema_version": 1,
                "request_id": request_id(),
                "action": "configure_screenshot_root",
                "source_root": str(tmp_path),
                "target_path": "/tmp/never-accepted",
            }
        ),
        paths=IntelligencePaths.from_root(tmp_path / "state"),
    )

    assert duplicate_response["error"]["code"] == "duplicate_json_key"
    assert unknown_response["error"]["code"] == "unknown_field"


def test_request_size_is_bounded(tmp_path: Path) -> None:
    response = handle_payload(
        b" " * (64 * 1024 + 1),
        paths=IntelligencePaths.from_root(tmp_path / "state"),
    )

    assert response["error"]["code"] == "request_too_large"


def test_configure_is_atomic_idempotent_and_rejects_request_reuse(tmp_path: Path) -> None:
    paths = IntelligencePaths.from_root(tmp_path / "state")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    identifier = request_id()
    original = configure_payload(first, identifier=identifier)

    first_response = execute_bytes(original, paths)
    repeated = execute_bytes(original, paths)
    reused = handle_payload(
        configure_payload(second, identifier=identifier), paths=paths
    )

    assert first_response == repeated
    assert reused["error"]["code"] == "request_id_reused"
    config = json.loads(paths.config.read_text(encoding="utf-8"))
    assert config["screenshot_root"] == str(first.resolve())


def test_configure_rejects_root_home_traversal_and_symlink(tmp_path: Path) -> None:
    paths = IntelligencePaths.from_root(tmp_path / "state")
    folder = tmp_path / "screenshots"
    folder.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(folder, target_is_directory=True)
    requests = (
        configure_payload(Path("/")),
        configure_payload(Path.home()),
        configure_payload(folder / ".." / "screenshots"),
        configure_payload(link),
    )

    codes = [handle_payload(item, paths=paths)["error"]["code"] for item in requests]

    assert codes == [
        "invalid_source_root",
        "invalid_source_root",
        "invalid_source_root",
        "unsafe_source_root",
    ]


def test_configure_rejects_app_state_and_workspace_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = IntelligencePaths.from_root(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "screenshots"
    nested.mkdir()
    monkeypatch.setenv("FROGANIZE_WORKSPACE", str(workspace))

    state_response = handle_payload(configure_payload(paths.root), paths=paths)
    workspace_response = handle_payload(configure_payload(nested), paths=paths)

    assert state_response["error"]["code"] == "source_root_overlap"
    assert workspace_response["error"]["code"] == "source_root_overlap"


def test_unicode_rename_creates_timeline_activity_without_file_content(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "截图 2026-08-12 10.20.30.PNG"
    source.write_bytes(b"private screenshot bytes")

    response = execute_bytes(rename_payload(source), paths)

    target = screenshots / str(response["renamed_name"])
    assert response["status"] == "renamed"
    assert target.name == "GitHub-项目-README-修改建议-20260812-102030.png"
    assert target.read_bytes() == b"private screenshot bytes"
    assert not source.exists()
    records = read_activity(paths)
    assert len(records) == 1
    assert records[0].event_type == EVENT_RENAME
    assert records[0].summary == "页面展示 README 修改建议。"
    assert "private screenshot bytes" not in paths.activity.read_text(encoding="utf-8")


def test_sensitive_analysis_uses_protected_name(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")

    response = execute_bytes(
        rename_payload(source, sensitive=True, category="文档"), paths
    )

    assert response["renamed_name"] == "敏感截图-文档-20260812-102030.png"


@pytest.mark.parametrize(
    ("source_name", "expected_code"),
    (
        ("../Screenshot 2026.png", "invalid_source_name"),
        ("nested/Screenshot 2026.png", "invalid_source_name"),
        ("Screenshot 2026.txt", "not_a_screenshot"),
        ("holiday.png", "not_a_screenshot"),
    ),
)
def test_source_name_and_screenshot_recognition_fail_closed(
    intelligence: tuple[IntelligencePaths, Path],
    source_name: str,
    expected_code: str,
) -> None:
    paths, _screenshots = intelligence
    fake = {
        "schema_version": 1,
        "request_id": request_id(),
        "action": "rename_screenshot",
        "source_name": source_name,
        "snapshot": {"device": 1, "inode": 1, "mode": 1, "size": 1, "mtime_ns": 1},
        "analysis": {
            "title": "safe",
            "summary": "",
            "category": "其他",
            "confidence": 1,
            "sensitive": False,
        },
        "provider": "test",
        "model": "test",
    }

    response = handle_payload(payload(fake), paths=paths)

    assert response["error"]["code"] == expected_code


def test_symlink_is_never_followed(intelligence: tuple[IntelligencePaths, Path]) -> None:
    paths, screenshots = intelligence
    outside = screenshots.parent / "outside.png"
    outside.write_bytes(b"outside")
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.symlink_to(outside)
    metadata = source.lstat()
    data = {
        "schema_version": 1,
        "request_id": request_id(),
        "action": "rename_screenshot",
        "source_name": source.name,
        "snapshot": {
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": metadata.st_mode,
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
        },
        "analysis": {
            "title": "safe",
            "summary": "",
            "category": "其他",
            "confidence": 1,
            "sensitive": False,
        },
        "provider": "test",
        "model": "test",
    }

    response = handle_payload(payload(data), paths=paths)

    assert response["error"]["code"] == "symbolic_link"
    assert outside.read_bytes() == b"outside"


@pytest.mark.parametrize(
    ("change", "expected_code"),
    (
        ("remove", "source_missing"),
        ("modify", "source_changed"),
    ),
)
def test_source_disappears_or_changes_after_ai_analysis(
    intelligence: tuple[IntelligencePaths, Path], change: str, expected_code: str
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    raw = rename_payload(source)
    if change == "remove":
        source.unlink()
    else:
        source.write_bytes(b"changed and longer")

    response = handle_payload(raw, paths=paths)

    assert response["error"]["code"] == expected_code
    assert read_activity(paths) == ()


@pytest.mark.parametrize(
    ("analysis_update", "expected_code"),
    (
        ({"confidence": 2}, "invalid_analysis"),
        ({"confidence": True}, "invalid_analysis"),
        ({"sensitive": "false"}, "invalid_analysis"),
        ({"title": ""}, "invalid_field"),
    ),
)
def test_invalid_ai_response_never_renames(
    intelligence: tuple[IntelligencePaths, Path],
    analysis_update: dict[str, object],
    expected_code: str,
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    data = json.loads(rename_payload(source))
    data["analysis"].update(analysis_update)

    response = handle_payload(payload(data), paths=paths)

    assert response["error"]["code"] == expected_code
    assert source.exists()


def test_ai_category_is_a_closed_enum(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")

    response = handle_payload(rename_payload(source, category="银行卡/../../外部"), paths=paths)

    assert response["error"]["code"] == "invalid_analysis"
    assert source.exists()


def test_invalid_filename_and_low_confidence_leave_source_unchanged(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    unsafe = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    low = screenshots / "Screen Shot 2026-08-12 at 10.20.31.png"
    unsafe.write_bytes(b"one")
    low.write_bytes(b"two")

    unsafe_response = handle_payload(rename_payload(unsafe, title="///：？！"), paths=paths)
    low_response = execute_bytes(rename_payload(low, confidence=0.2), paths)

    assert unsafe_response["error"]["code"] == "invalid_filename"
    assert low_response["status"] == "skipped"
    assert low_response["reason_code"] == "low_confidence"
    assert unsafe.exists() and low.exists()


def test_long_unicode_title_stays_under_filesystem_limit(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.webp"
    source.write_bytes(b"image")

    response = execute_bytes(rename_payload(source, title="整理魔法" * 100), paths)

    renamed = str(response["renamed_name"])
    assert len(renamed.encode("utf-8")) <= 240
    assert renamed.endswith(".webp")
    assert (screenshots / renamed).exists()


def test_case_insensitive_collision_and_two_quick_screenshots_are_safe(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    first = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    second = screenshots / "Screenshot 2026-08-12 at 10.20.31.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    occupied = screenshots / "GITHUB-项目-README-修改建议-20260812-102030.PNG"
    occupied.write_bytes(b"existing")

    first_response = execute_bytes(rename_payload(first), paths)
    second_response = execute_bytes(rename_payload(second), paths)

    assert first_response["renamed_name"].endswith("-2.png")
    assert second_response["renamed_name"].endswith("-3.png")
    assert occupied.read_bytes() == b"existing"
    assert (screenshots / str(first_response["renamed_name"])).read_bytes() == b"first"
    assert (screenshots / str(second_response["renamed_name"])).read_bytes() == b"second"


def test_duplicate_request_is_idempotent_and_reuse_is_rejected(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    identifier = request_id()
    raw = rename_payload(source, identifier=identifier)

    first = execute_bytes(raw, paths)
    repeated = execute_bytes(raw, paths)
    changed = json.loads(raw)
    changed["analysis"]["title"] = "different"
    reused = handle_payload(payload(changed), paths=paths)

    assert repeated == first
    assert len(read_activity(paths)) == 1
    assert reused["error"]["code"] == "request_id_reused"


def test_undo_by_event_and_latest_survive_state_reload(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    first = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    second = screenshots / "Screenshot 2026-08-12 at 10.20.31.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    first_result = execute_bytes(rename_payload(first, title="first"), paths)
    second_result = execute_bytes(rename_payload(second, title="second"), paths)

    explicit = execute_bytes(undo_payload(event_id=str(first_result["event_id"])), paths)
    latest = execute_bytes(undo_payload(), IntelligencePaths.from_root(paths.root))

    assert explicit["status"] == "undone"
    assert latest["status"] == "undone"
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert [record.event_type for record in read_activity(paths)] == [
        EVENT_RENAME,
        EVENT_RENAME,
        EVENT_UNDO,
        EVENT_UNDO,
    ]


def test_repeated_undo_and_unknown_event_are_clear(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    renamed = execute_bytes(rename_payload(source), paths)
    execute_bytes(undo_payload(event_id=str(renamed["event_id"])), paths)

    repeated = execute_bytes(undo_payload(event_id=str(renamed["event_id"])), paths)
    unknown = handle_payload(undo_payload(event_id=request_id()), paths=paths)

    assert repeated["status"] == "skipped"
    assert repeated["reason_code"] == "already_undone"
    assert unknown["error"]["code"] == "event_not_found"


def test_undo_conflict_and_modified_renamed_file_do_not_overwrite(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    conflict_source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    changed_source = screenshots / "Screenshot 2026-08-12 at 10.20.31.png"
    conflict_source.write_bytes(b"first")
    changed_source.write_bytes(b"second")
    conflict_rename = execute_bytes(rename_payload(conflict_source, title="first"), paths)
    changed_rename = execute_bytes(rename_payload(changed_source, title="second"), paths)
    conflict_source.write_bytes(b"new occupant")
    changed_target = screenshots / str(changed_rename["renamed_name"])
    changed_target.write_bytes(b"edited after rename")

    conflict = handle_payload(
        undo_payload(event_id=str(conflict_rename["event_id"])), paths=paths
    )
    changed = handle_payload(
        undo_payload(event_id=str(changed_rename["event_id"])), paths=paths
    )

    assert conflict["error"]["code"] == "original_conflict"
    assert conflict_source.read_bytes() == b"new occupant"
    assert changed["error"]["code"] == "source_changed"
    assert changed_target.read_bytes() == b"edited after rename"


def test_activity_write_failure_rolls_back_rename(
    intelligence: tuple[IntelligencePaths, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")

    def fail_activity(*_args, **_kwargs) -> None:
        raise IntelligenceStorageError("activity_write_failed", "simulated")

    monkeypatch.setattr(operations, "append_activity", fail_activity)
    response = handle_payload(rename_payload(source), paths=paths)

    assert response["error"]["code"] == "activity_write_failed"
    assert source.read_bytes() == b"image"
    assert list(paths.pending.iterdir()) == []
    assert read_activity(paths) == ()


def test_activity_write_failure_rolls_back_undo(
    intelligence: tuple[IntelligencePaths, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    renamed = execute_bytes(rename_payload(source), paths)
    target = screenshots / str(renamed["renamed_name"])
    real_append = operations.append_activity

    def fail_undo_activity(_paths, record) -> None:
        if record.event_type == EVENT_UNDO:
            raise IntelligenceStorageError("activity_write_failed", "simulated")
        real_append(_paths, record)

    monkeypatch.setattr(operations, "append_activity", fail_undo_activity)
    response = handle_payload(undo_payload(event_id=str(renamed["event_id"])), paths=paths)

    assert response["error"]["code"] == "activity_write_failed"
    assert not source.exists()
    assert target.read_bytes() == b"image"
    assert len(read_activity(paths)) == 1


def test_no_replace_rename_failure_keeps_source(
    intelligence: tuple[IntelligencePaths, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")

    def fail_rename(_source: Path, destination: Path) -> None:
        raise OSError(errno.EBUSY, "busy", destination)

    monkeypatch.setattr(operations, "_rename_no_replace", fail_rename)
    response = handle_payload(rename_payload(source), paths=paths)

    assert response["error"]["code"] == "source_busy"
    assert source.read_bytes() == b"image"
    assert list(paths.pending.iterdir()) == []


def test_uncommitted_post_move_journal_is_recovered_by_rollback(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    request = parse_request_bytes(rename_payload(source))
    assert isinstance(request, RenameScreenshotRequest)
    target = screenshots / "safe-20260812-102030.png"
    record = new_rename_record(
        request_id=request.request_id,
        request_fingerprint=request_fingerprint(request),
        source_root=screenshots,
        original_name=source.name,
        renamed_name=target.name,
        snapshot=request.snapshot,
        analysis=request.analysis,
        provider=request.provider,
        model=request.model,
    )
    operations._write_journal(
        paths,
        request_id=request.request_id,
        request_fingerprint_value=request_fingerprint(request),
        source_root=screenshots,
        source_name=source.name,
        target_name=target.name,
        snapshot=request.snapshot,
        activity=record,
    )
    operations._rename_no_replace(source, target)

    recover_pending_operations(paths, (), screenshots)

    assert source.read_bytes() == b"image"
    assert not target.exists()
    assert list(paths.pending.iterdir()) == []


def test_tampered_journal_cannot_recover_outside_authorized_root(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"authorized")
    request = parse_request_bytes(rename_payload(source))
    assert isinstance(request, RenameScreenshotRequest)
    target = screenshots / "safe-20260812-102030.png"
    record = new_rename_record(
        request_id=request.request_id,
        request_fingerprint=request_fingerprint(request),
        source_root=screenshots,
        original_name=source.name,
        renamed_name=target.name,
        snapshot=request.snapshot,
        analysis=request.analysis,
        provider=request.provider,
        model=request.model,
    )
    journal_path = operations._write_journal(
        paths,
        request_id=request.request_id,
        request_fingerprint_value=request_fingerprint(request),
        source_root=screenshots,
        source_name=source.name,
        target_name=target.name,
        snapshot=request.snapshot,
        activity=record,
    )
    outside = screenshots.parent / "outside"
    outside.mkdir()
    outside_file = outside / source.name
    outside_file.write_bytes(b"must not move")
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    raw["source_root"] = str(outside)
    raw["activity"]["source_root"] = str(outside)
    journal_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(operations.ScreenshotOperationError, match="outside"):
        recover_pending_operations(paths, (), screenshots)

    assert outside_file.read_bytes() == b"must not move"
    assert source.read_bytes() == b"authorized"


def test_damaged_activity_blocks_mutation(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    paths.activity.write_text("{bad\n", encoding="utf-8")
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")

    response = handle_payload(rename_payload(source), paths=paths)

    assert response["error"]["code"] == "damaged_activity"
    assert source.read_bytes() == b"image"


def test_state_override_matches_macos_application_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preferred = tmp_path / "preferred"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("FROGANIZE_STATE_DIR", str(preferred))
    monkeypatch.setenv("FROGANIZE_APP_SUPPORT_ROOT", str(legacy))

    assert default_paths().root == preferred.resolve(strict=False)


def test_read_only_status_does_not_create_state(tmp_path: Path) -> None:
    paths = IntelligencePaths.from_root(tmp_path / "absent-state")

    status = get_intelligence_status(paths)

    assert status.configured is False
    assert status.problem is None
    assert not paths.root.exists()


def test_read_only_status_projects_latest_activity_and_outstanding_count(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    source.write_bytes(b"image")
    renamed = execute_bytes(rename_payload(source), paths)

    before_undo = get_intelligence_status(paths)
    execute_bytes(undo_payload(event_id=str(renamed["event_id"])), paths)
    after_undo = get_intelligence_status(paths)

    assert before_undo.configured is True
    assert before_undo.screenshot_root == screenshots
    assert before_undo.latest_renamed_name == renamed["renamed_name"]
    assert before_undo.latest_success_time is not None
    assert before_undo.outstanding_rename_count == 1
    assert after_undo.outstanding_rename_count == 0
    assert after_undo.latest_renamed_name is None
    assert after_undo.latest_success_time is None
    assert after_undo.recent_activity[0].event_type == EVENT_UNDO


def test_read_only_status_uses_latest_outstanding_not_latest_undone_rename(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    first_source = screenshots / "Screenshot 2026-08-12 at 10.20.30.png"
    second_source = screenshots / "Screenshot 2026-08-12 at 10.20.31.png"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    first = execute_bytes(rename_payload(first_source, title="first"), paths)
    second = execute_bytes(rename_payload(second_source, title="second"), paths)

    execute_bytes(undo_payload(event_id=str(second["event_id"])), paths)
    status = get_intelligence_status(paths)

    assert status.outstanding_rename_count == 1
    assert status.latest_renamed_name == first["renamed_name"]
    assert status.latest_success_time is not None
    assert status.recent_activity[0].event_type == EVENT_UNDO


def test_read_only_status_reports_damaged_activity_without_losing_configuration(
    intelligence: tuple[IntelligencePaths, Path],
) -> None:
    paths, screenshots = intelligence
    paths.activity.write_text("{damaged\n", encoding="utf-8")

    status = get_intelligence_status(paths)

    assert status.configured is True
    assert status.screenshot_root == screenshots
    assert status.problem is not None
