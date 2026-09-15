"""Workspace initialization, validation, and mutation locking."""

from __future__ import annotations

import json
import os
import socket
import stat
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType

from dropnest.config import load_config, new_config, write_config_atomic
from dropnest.exceptions import (
    ConfigurationError,
    WorkspaceError,
    WorkspaceLockError,
    WorkspaceSafetyError,
)
from dropnest.models import InitResult, Workspace

INBOX_NAME = "Inbox"
TIMELINE_NAME = "Timeline"
METADATA_NAME = ".dropnest"
CONFIG_NAME = "config.json"
HISTORY_NAME = "history.jsonl"
LOCK_NAME = "workspace.lock"


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_workspace_root(
    path: str | os.PathLike[str],
    *,
    home: Path | None = None,
) -> Path:
    """Resolve an explicit candidate root and reject dangerous locations."""
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise WorkspaceSafetyError("Workspace paths may not contain '..'.")
    absolute = _absolute_without_resolving(raw)
    if absolute == Path(absolute.anchor):
        raise WorkspaceSafetyError("The filesystem root cannot be a workspace.")

    protected_home = _absolute_without_resolving(home or Path.home())
    protected_desktop = protected_home / "Desktop"
    if absolute == protected_home:
        raise WorkspaceSafetyError("The user home directory cannot be a workspace.")
    if absolute == protected_desktop:
        raise WorkspaceSafetyError("The Desktop directory cannot be a workspace.")
    if absolute.is_symlink():
        raise WorkspaceSafetyError("The workspace root cannot be a symbolic link.")

    resolved = absolute.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise WorkspaceSafetyError("The filesystem root cannot be a workspace.")
    if resolved in {protected_home.resolve(strict=False), protected_desktop.resolve(strict=False)}:
        raise WorkspaceSafetyError("The resolved workspace is a protected directory.")
    return resolved


def workspace_paths(root: Path) -> Workspace:
    """Derive the fixed MVP paths below a resolved root."""
    metadata = root / METADATA_NAME
    return Workspace(
        root=root,
        inbox=root / INBOX_NAME,
        timeline=root / TIMELINE_NAME,
        metadata=metadata,
        config=metadata / CONFIG_NAME,
        history=metadata / HISTORY_NAME,
        lock=metadata / LOCK_NAME,
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_relationships(workspace: Workspace) -> None:
    """Validate containment and non-overlap for managed paths."""
    root = workspace.root.resolve(strict=False)
    inbox = workspace.inbox.resolve(strict=False)
    timeline = workspace.timeline.resolve(strict=False)
    metadata = workspace.metadata.resolve(strict=False)
    for label, path in (
        ("Inbox", inbox),
        ("Timeline", timeline),
        (".dropnest", metadata),
        ("configuration", workspace.config.resolve(strict=False)),
        ("history", workspace.history.resolve(strict=False)),
        ("lock", workspace.lock.resolve(strict=False)),
    ):
        if not _is_within(path, root) or path == root:
            raise WorkspaceSafetyError(f"{label} must be contained by the workspace.")
    if inbox == timeline:
        raise WorkspaceSafetyError("Inbox and Timeline must be different directories.")
    if _is_within(inbox, timeline) or _is_within(timeline, inbox):
        raise WorkspaceSafetyError("Inbox and Timeline may not contain each other.")


def _require_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise WorkspaceSafetyError(f"{label} cannot be a symbolic link: {path}")
    if not path.exists():
        raise WorkspaceError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise WorkspaceError(f"{label} is not a directory: {path}")
    if not os.access(path, os.R_OK | os.X_OK):
        raise WorkspaceError(f"{label} is not readable: {path}")


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise WorkspaceSafetyError(f"{label} cannot be a symbolic link: {path}")
    if not path.exists():
        raise WorkspaceError(f"{label} does not exist: {path}")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise WorkspaceError(f"Cannot inspect {label}: {path}") from exc
    if not stat.S_ISREG(mode):
        raise WorkspaceError(f"{label} is not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise WorkspaceError(f"{label} is not readable: {path}")


def validate_workspace(
    path: str | os.PathLike[str],
    *,
    require_writable: bool = False,
    validate_configuration: bool = True,
    require_inbox: bool = True,
) -> Workspace:
    """Return a fully validated, existing workspace."""
    root = resolve_workspace_root(path)
    workspace = workspace_paths(root)
    validate_relationships(workspace)
    _require_directory(root, "Workspace")
    if require_inbox:
        _require_directory(workspace.inbox, "Inbox")
    _require_directory(workspace.timeline, "Timeline")
    _require_directory(workspace.metadata, ".dropnest")
    _require_regular_file(workspace.config, "Configuration")
    _require_regular_file(workspace.history, "History")
    if validate_configuration:
        load_config(workspace.config)
    if require_writable:
        managed_paths = [
            ("Timeline", workspace.timeline),
            (".dropnest", workspace.metadata),
        ]
        if require_inbox:
            managed_paths.insert(0, ("Inbox", workspace.inbox))
        for label, managed in managed_paths:
            if not os.access(managed, os.W_OK):
                raise WorkspaceError(f"{label} is not writable: {managed}")
    return workspace


def validate_desktop_source(
    path: str | os.PathLike[str],
    workspace: Workspace,
    *,
    require_writable: bool = False,
) -> Path:
    """Validate one fixed external source without allowing workspace overlap."""
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise WorkspaceSafetyError("Desktop source paths may not contain '..'.")
    absolute = _absolute_without_resolving(raw)
    if absolute in {Path(absolute.anchor), _absolute_without_resolving(Path.home())}:
        raise WorkspaceSafetyError(
            "The filesystem root and home directory cannot be Desktop sources."
        )
    if absolute.is_symlink():
        raise WorkspaceSafetyError("The Desktop source cannot be a symbolic link.")
    _require_directory(absolute, "Desktop source")
    resolved = absolute.resolve()
    workspace_root = workspace.root.resolve()
    timeline = workspace.timeline.resolve()
    if (
        _is_within(resolved, workspace_root)
        or _is_within(workspace_root, resolved)
        or _is_within(resolved, timeline)
        or _is_within(timeline, resolved)
    ):
        raise WorkspaceSafetyError(
            "Desktop source and DropNest workspace may not contain each other."
        )
    if require_writable and not os.access(resolved, os.W_OK):
        raise WorkspaceError(f"Desktop source is not writable: {resolved}")
    return resolved


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class WorkspaceLock:
    """Small PID lock whose stale file is reclaimed after a crashed owner."""

    def __init__(self, workspace: Workspace) -> None:
        self.path = workspace.lock
        self.token = uuid.uuid4().hex
        self._owned = False

    def _owner_is_active(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            hostname = str(data["hostname"])
            created_at = datetime.fromisoformat(
                str(data["created_at"]).replace("Z", "+00:00")
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False
        if created_at.tzinfo is None:
            return False
        if datetime.now(UTC) - created_at >= timedelta(hours=24):
            return False
        if hostname != socket.gethostname():
            return True
        return _pid_is_running(pid)

    def acquire(self) -> None:
        payload = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "token": self.token,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        temporary = self.path.with_name(f".{self.path.name}-{self.token}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise WorkspaceLockError(
                f"Cannot prepare workspace lock: {self.path}"
            ) from exc

        for _ in range(3):
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                if self._owner_is_active():
                    temporary.unlink(missing_ok=True)
                    raise WorkspaceLockError(
                        f"Workspace is locked by another operation: {self.path}"
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    temporary.unlink(missing_ok=True)
                    raise WorkspaceLockError(
                        f"Cannot remove stale workspace lock: {self.path}"
                    ) from exc
                continue
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise WorkspaceLockError(
                    f"Cannot create workspace lock: {self.path}"
                ) from exc
            temporary.unlink(missing_ok=True)
            self._owned = True
            return
        temporary.unlink(missing_ok=True)
        raise WorkspaceLockError(f"Could not acquire workspace lock: {self.path}")

    def release(self) -> None:
        if not self._owned:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
        finally:
            self._owned = False

    def __enter__(self) -> WorkspaceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def _create_directory(path: Path, created: list[Path], preserved: list[Path]) -> None:
    if path.is_symlink():
        raise WorkspaceSafetyError(f"Managed directory cannot be a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise WorkspaceError(f"Expected a directory but found another item: {path}")
        preserved.append(path)
        return
    path.mkdir()
    created.append(path)


def initialize_workspace(
    path: str | os.PathLike[str],
    *,
    force_config: bool = False,
) -> InitResult:
    """Create a fixed-layout workspace without deleting or silently overwriting."""
    root = resolve_workspace_root(path)
    created: list[Path] = []
    preserved: list[Path] = []
    updated: list[Path] = []
    if root.exists():
        if not root.is_dir():
            raise WorkspaceError(f"Workspace path is not a directory: {root}")
        preserved.append(root)
    else:
        root.mkdir(parents=True)
        created.append(root)

    workspace = workspace_paths(root)
    for managed in (workspace.inbox, workspace.timeline, workspace.metadata):
        if managed.is_symlink():
            raise WorkspaceSafetyError(
                f"Managed directory cannot be a symbolic link: {managed}"
            )
    validate_relationships(workspace)
    _create_directory(workspace.metadata, created, preserved)

    with WorkspaceLock(workspace):
        _create_directory(workspace.inbox, created, preserved)
        _create_directory(workspace.timeline, created, preserved)

        if workspace.config.is_symlink():
            raise WorkspaceSafetyError(
                f"Configuration cannot be a symbolic link: {workspace.config}"
            )
        config_existed = workspace.config.exists()
        if config_existed and not force_config:
            if not workspace.config.is_file():
                raise ConfigurationError(
                    f"Configuration is not a regular file: {workspace.config}"
                )
            load_config(workspace.config)
            preserved.append(workspace.config)
        else:
            write_config_atomic(workspace.config, new_config())
            if config_existed:
                updated.append(workspace.config)
            else:
                created.append(workspace.config)

        if workspace.history.is_symlink():
            raise WorkspaceSafetyError(
                f"History cannot be a symbolic link: {workspace.history}"
            )
        if workspace.history.exists():
            if not workspace.history.is_file():
                raise WorkspaceError(
                    f"History is not a regular file: {workspace.history}"
                )
            preserved.append(workspace.history)
        else:
            try:
                workspace.history.touch(exist_ok=False)
            except OSError as exc:
                raise WorkspaceError(
                    f"Could not create history: {workspace.history}"
                ) from exc
            created.append(workspace.history)

    validate_workspace(root)
    return InitResult(
        workspace,
        tuple(created),
        tuple(preserved),
        tuple(updated),
    )
