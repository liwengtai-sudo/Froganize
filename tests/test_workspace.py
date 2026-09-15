"""Workspace initialization and safety tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dropnest.config import load_config
from dropnest.exceptions import (
    ConfigurationError,
    WorkspaceError,
    WorkspaceLockError,
    WorkspaceSafetyError,
)
from dropnest.models import Workspace
from dropnest.workspace import (
    WorkspaceLock,
    initialize_workspace,
    resolve_workspace_root,
    validate_relationships,
    validate_workspace,
    workspace_paths,
)


def test_initialize_creates_valid_workspace(tmp_path: Path) -> None:
    root = tmp_path / "DropNest Workspace"

    result = initialize_workspace(root)

    assert result.workspace.root == root.resolve()
    assert result.workspace.inbox.is_dir()
    assert result.workspace.timeline.is_dir()
    assert result.workspace.metadata.is_dir()
    assert result.workspace.history.read_text(encoding="utf-8") == ""
    config = load_config(result.workspace.config)
    assert config["schema_version"] == 1
    assert config["time_strategy"] == "mtime"
    assert config["archive_layout"] == "YYYY/YYYY-MM"
    assert config["folder_strategy"] == "whole"
    assert not result.workspace.lock.exists()
    assert validate_workspace(root) == result.workspace


def test_initialize_is_idempotent_and_preserves_content(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    first = initialize_workspace(root)
    marker = first.workspace.inbox / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    original_config = first.workspace.config.read_text(encoding="utf-8")

    second = initialize_workspace(root)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert second.workspace.config.read_text(encoding="utf-8") == original_config
    assert second.created == ()


def test_initialize_does_not_silently_replace_damaged_config(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    workspace.config.write_text("{broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="damaged"):
        initialize_workspace(workspace.root)

    assert workspace.config.read_text(encoding="utf-8") == "{broken"


def test_force_config_explicitly_replaces_config(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    old_id = load_config(workspace.config)["workspace_id"]

    result = initialize_workspace(workspace.root, force_config=True)

    assert load_config(workspace.config)["workspace_id"] != old_id
    assert result.updated == (workspace.config,)


def test_rejects_root_without_touching_it() -> None:
    with pytest.raises(WorkspaceSafetyError, match="root"):
        resolve_workspace_root(Path(Path.cwd().anchor))


def test_rejects_home_and_desktop_using_temp_protected_paths(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"

    with pytest.raises(WorkspaceSafetyError, match="home"):
        resolve_workspace_root(fake_home, home=fake_home)
    with pytest.raises(WorkspaceSafetyError, match="Desktop"):
        resolve_workspace_root(fake_home / "Desktop", home=fake_home)


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    candidate = tmp_path / "safe" / ".." / "escaped"

    with pytest.raises(WorkspaceSafetyError, match=r"\.\."):
        resolve_workspace_root(candidate)


def test_rejects_workspace_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked-workspace"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(WorkspaceSafetyError, match="symbolic link"):
        initialize_workspace(link)


def test_rejects_managed_directory_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "Inbox").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceSafetyError, match="symbolic link"):
        initialize_workspace(root)


def test_relationship_validation_rejects_same_and_nested_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    base = workspace_paths(root)
    same = Workspace(
        root,
        base.inbox,
        base.inbox,
        base.metadata,
        base.config,
        base.history,
        base.lock,
    )
    nested = Workspace(
        root,
        base.inbox,
        base.inbox / "Timeline",
        base.metadata,
        base.config,
        base.history,
        base.lock,
    )

    with pytest.raises(WorkspaceSafetyError, match="different"):
        validate_relationships(same)
    with pytest.raises(WorkspaceSafetyError, match="contain"):
        validate_relationships(nested)


def test_active_lock_blocks_and_release_allows_next_owner(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace

    with WorkspaceLock(workspace):
        with pytest.raises(WorkspaceLockError, match="locked"):
            WorkspaceLock(workspace).acquire()

    with WorkspaceLock(workspace):
        assert workspace.lock.exists()
    assert not workspace.lock.exists()


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    workspace.lock.write_text(
        json.dumps(
            {
                "pid": 999_999_999,
                "hostname": __import__("socket").gethostname(),
                "token": "stale",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with WorkspaceLock(workspace):
        owner = json.loads(workspace.lock.read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid()

    assert not workspace.lock.exists()


def test_init_metadata_change_is_blocked_by_active_lock(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace

    with WorkspaceLock(workspace):
        with pytest.raises(WorkspaceLockError, match="locked"):
            initialize_workspace(workspace.root, force_config=True)


def test_writable_validation_reports_permission_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    real_access = os.access

    def fake_access(path: os.PathLike[str], mode: int) -> bool:
        if Path(path) == workspace.timeline and mode == os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    with pytest.raises(WorkspaceError, match="Timeline is not writable"):
        validate_workspace(workspace.root, require_writable=True)
