"""Minimal versioned workspace configuration."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dropnest.exceptions import ConfigurationError

CONFIG_SCHEMA_VERSION = 1
TIME_STRATEGY = "mtime"
ARCHIVE_LAYOUT = "YYYY/YYYY-MM"
FOLDER_STRATEGY = "whole"

_REQUIRED_FIELDS = {
    "schema_version",
    "workspace_id",
    "initialized_at",
    "time_strategy",
    "archive_layout",
    "folder_strategy",
}


def new_config() -> dict[str, Any]:
    """Return a new minimal MVP configuration."""
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "workspace_id": str(uuid.uuid4()),
        "initialized_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "time_strategy": TIME_STRATEGY,
        "archive_layout": ARCHIVE_LAYOUT,
        "folder_strategy": FOLDER_STRATEGY,
    }


def validate_config(data: object) -> dict[str, Any]:
    """Validate and return a configuration mapping."""
    if not isinstance(data, dict):
        raise ConfigurationError("Configuration must be a JSON object.")
    missing = _REQUIRED_FIELDS.difference(data)
    if missing:
        names = ", ".join(sorted(missing))
        raise ConfigurationError(f"Configuration is missing fields: {names}.")
    if (
        not isinstance(data["schema_version"], int)
        or isinstance(data["schema_version"], bool)
        or data["schema_version"] != CONFIG_SCHEMA_VERSION
    ):
        raise ConfigurationError(
            f"Unsupported configuration schema: {data['schema_version']!r}."
        )
    try:
        if not isinstance(data["workspace_id"], str):
            raise ValueError
        uuid.UUID(data["workspace_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ConfigurationError("Configuration has an invalid workspace_id.") from exc
    try:
        if not isinstance(data["initialized_at"], str):
            raise ValueError
        initialized_at = datetime.fromisoformat(
            data["initialized_at"].replace("Z", "+00:00")
        )
        if initialized_at.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise ConfigurationError(
            "Configuration has an invalid initialized_at timestamp."
        ) from exc
    expected = {
        "time_strategy": TIME_STRATEGY,
        "archive_layout": ARCHIVE_LAYOUT,
        "folder_strategy": FOLDER_STRATEGY,
    }
    for field, value in expected.items():
        if data[field] != value:
            raise ConfigurationError(
                f"Unsupported {field}: {data[field]!r}; expected {value!r}."
            )
    return data


def load_config(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON configuration with readable errors."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration does not exist: {path}") from exc
    except PermissionError as exc:
        raise ConfigurationError(f"Configuration is not readable: {path}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"Configuration is damaged: {path}") from exc
    return validate_config(data)


def write_config_atomic(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace a configuration after writing and syncing a temp file."""
    validate_config(data)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".config-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        raise ConfigurationError(f"Could not write configuration: {path}") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
