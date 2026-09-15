"""Versioned append-only JSON Lines history and undo selection."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dropnest.exceptions import HistoryError
from dropnest.models import (
    HistoryBatch,
    HistoryCalendar,
    HistoryItem,
    ItemType,
    Workspace,
)

HISTORY_SCHEMA_VERSION = 1
EVENT_SORT = "sort"
EVENT_UNDO = "undo"
RESULT_SUCCESS = "success"
RESULT_FAILED = "failed"

_REQUIRED_FIELDS = {
    "schema_version",
    "event_id",
    "batch_id",
    "event_type",
    "timestamp",
    "source_path",
    "destination_path",
    "item_type",
    "classification_time",
    "result",
    "undo_of_event_id",
}


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """One validated move or undo outcome."""

    schema_version: int
    event_id: str
    batch_id: str
    event_type: str
    timestamp: str
    source_path: str
    destination_path: str
    item_type: str
    classification_time: str
    result: str
    undo_of_event_id: str | None


def utc_now_text() -> str:
    """Return a stable ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_batch_id() -> str:
    """Return a unique command batch ID."""
    return uuid.uuid4().hex


def new_record(
    *,
    batch_id: str,
    event_type: str,
    source: Path,
    destination: Path,
    item_type: ItemType,
    classification_time: str,
    result: str,
    undo_of_event_id: str | None = None,
) -> HistoryRecord:
    """Create a validated history record."""
    record = HistoryRecord(
        schema_version=HISTORY_SCHEMA_VERSION,
        event_id=str(uuid.uuid4()),
        batch_id=batch_id,
        event_type=event_type,
        timestamp=utc_now_text(),
        source_path=str(source),
        destination_path=str(destination),
        item_type=item_type.value,
        classification_time=classification_time,
        result=result,
        undo_of_event_id=undo_of_event_id,
    )
    validate_record(asdict(record))
    return record


def _parse_datetime(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise HistoryError(f"History field {field} must be a string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise HistoryError(f"History field {field} is not a valid timestamp.") from exc


def validate_record(data: object) -> HistoryRecord:
    """Validate untrusted JSON and return a typed record."""
    if not isinstance(data, dict):
        raise HistoryError("History record must be a JSON object.")
    missing = _REQUIRED_FIELDS.difference(data)
    if missing:
        raise HistoryError(
            "History record is missing fields: " + ", ".join(sorted(missing)) + "."
        )
    if (
        not isinstance(data["schema_version"], int)
        or isinstance(data["schema_version"], bool)
        or data["schema_version"] != HISTORY_SCHEMA_VERSION
    ):
        raise HistoryError(
            f"Unsupported history schema: {data['schema_version']!r}."
        )
    for field in ("event_id", "batch_id"):
        try:
            if not isinstance(data[field], str):
                raise ValueError
            uuid.UUID(data[field])
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryError(f"History field {field} is not a valid ID.") from exc
    if data["event_type"] not in {EVENT_SORT, EVENT_UNDO}:
        raise HistoryError(f"Unknown history event_type: {data['event_type']!r}.")
    if data["result"] not in {RESULT_SUCCESS, RESULT_FAILED}:
        raise HistoryError(f"Unknown history result: {data['result']!r}.")
    if data["item_type"] not in {kind.value for kind in ItemType}:
        raise HistoryError(f"Unknown history item_type: {data['item_type']!r}.")
    for field in ("source_path", "destination_path"):
        value = data[field]
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise HistoryError(f"History field {field} must be an absolute path.")
    _parse_datetime(data["timestamp"], "timestamp")
    _parse_datetime(data["classification_time"], "classification_time")
    undo_of = data["undo_of_event_id"]
    if data["event_type"] == EVENT_UNDO:
        try:
            uuid.UUID(str(undo_of))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryError("Undo history requires a valid undo_of_event_id.") from exc
    elif undo_of is not None:
        raise HistoryError("Sort history cannot contain undo_of_event_id.")
    return HistoryRecord(
        **{field: data[field] for field in HistoryRecord.__dataclass_fields__}
    )


def _source_roots(
    workspace: Workspace,
    additional: tuple[Path, ...],
) -> tuple[Path, ...]:
    roots = {workspace.inbox.resolve(strict=False)}
    roots.update(path.resolve(strict=False) for path in additional)
    return tuple(sorted(roots, key=str))


def _ensure_record_paths_are_safe(
    workspace: Workspace,
    record: HistoryRecord,
    *,
    source_roots: tuple[Path, ...] = (),
) -> None:
    resolved: dict[str, Path] = {}
    for field, value in (
        ("source_path", record.source_path),
        ("destination_path", record.destination_path),
    ):
        path = Path(value)
        if ".." in path.parts:
            raise HistoryError(f"History {field} contains path traversal: {path}")
        resolved[field] = path.resolve(strict=False)

    allowed_sources = _source_roots(workspace, source_roots)
    timeline = workspace.timeline.resolve(strict=False)
    if record.event_type == EVENT_SORT:
        if resolved["source_path"].parent not in allowed_sources:
            raise HistoryError(
                "Sort history source is not a direct child of an allowed source."
            )
        try:
            resolved["destination_path"].relative_to(timeline)
        except ValueError as exc:
            raise HistoryError("Sort history destination is outside Timeline.") from exc
    else:
        try:
            resolved["source_path"].relative_to(timeline)
        except ValueError as exc:
            raise HistoryError("Undo history source is outside Timeline.") from exc
        if resolved["destination_path"].parent not in allowed_sources:
            raise HistoryError(
                "Undo history destination is not a direct child of an allowed source."
            )


def read_history(
    workspace: Workspace,
    *,
    source_roots: tuple[Path, ...] = (),
) -> tuple[HistoryRecord, ...]:
    """Read every record strictly; one malformed line invalidates the history."""
    records: list[HistoryRecord] = []
    try:
        with workspace.history.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise HistoryError(f"History line {line_number} is blank.")
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise HistoryError(
                        f"History line {line_number} is damaged."
                    ) from exc
                try:
                    record = validate_record(raw)
                    _ensure_record_paths_are_safe(
                        workspace,
                        record,
                        source_roots=source_roots,
                    )
                except HistoryError as exc:
                    raise HistoryError(
                        f"Invalid history line {line_number}: {exc}"
                    ) from exc
                records.append(record)
    except FileNotFoundError as exc:
        raise HistoryError(f"History does not exist: {workspace.history}") from exc
    except PermissionError as exc:
        raise HistoryError(f"History is not readable: {workspace.history}") from exc
    except UnicodeDecodeError as exc:
        raise HistoryError(f"History is not valid UTF-8: {workspace.history}") from exc
    return tuple(records)


def append_history(
    workspace: Workspace,
    record: HistoryRecord,
    *,
    source_roots: tuple[Path, ...] = (),
) -> None:
    """Append and fsync exactly one validated JSON record."""
    validate_record(asdict(record))
    _ensure_record_paths_are_safe(
        workspace,
        record,
        source_roots=source_roots,
    )
    encoded = json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with workspace.history.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise HistoryError(f"Could not append history: {workspace.history}") from exc


def latest_sort_records(
    records: tuple[HistoryRecord, ...],
    *,
    source_root: Path | None = None,
) -> tuple[HistoryRecord, ...]:
    """Return successful moves from the latest batch for one source flow."""
    resolved_source = (
        source_root.resolve(strict=False) if source_root is not None else None
    )

    def belongs_to_source(record: HistoryRecord) -> bool:
        if resolved_source is None:
            return True
        return Path(record.source_path).parent.resolve(strict=False) == resolved_source

    latest_batch: str | None = None
    for record in records:
        if (
            record.event_type == EVENT_SORT
            and record.result == RESULT_SUCCESS
            and belongs_to_source(record)
        ):
            latest_batch = record.batch_id
    if latest_batch is None:
        return ()
    return tuple(
        record
        for record in records
        if record.event_type == EVENT_SORT
        and record.result == RESULT_SUCCESS
        and belongs_to_source(record)
        and record.batch_id == latest_batch
    )


def outstanding_latest_sort_records(
    records: tuple[HistoryRecord, ...],
    *,
    source_root: Path | None = None,
) -> tuple[HistoryRecord, ...]:
    """Return only not-yet-restored moves from the latest sort batch."""
    latest = latest_sort_records(records, source_root=source_root)
    if not latest:
        return ()
    restored = {
        record.undo_of_event_id
        for record in records
        if record.event_type == EVENT_UNDO and record.result == RESULT_SUCCESS
    }
    return tuple(record for record in latest if record.event_id not in restored)


def _history_datetime(value: str) -> datetime:
    """Parse a timestamp already validated by ``read_history``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def project_history_calendar(
    records: tuple[HistoryRecord, ...],
    *,
    source_root: Path,
) -> HistoryCalendar:
    """Project validated records into read-only Desktop organization batches.

    The projection deliberately exposes only successful sort events whose
    original path is a direct child of ``source_root``. Older batches remain
    visible, but only the outstanding latest batch is marked undoable because
    that is the executor's safety contract.
    """
    resolved_source = source_root.resolve(strict=False)
    sort_records = tuple(
        record
        for record in records
        if record.event_type == EVENT_SORT
        and record.result == RESULT_SUCCESS
        and Path(record.source_path).parent.resolve(strict=False) == resolved_source
    )
    if not sort_records:
        return HistoryCalendar((), None)

    restored = {
        record.undo_of_event_id
        for record in records
        if record.event_type == EVENT_UNDO and record.result == RESULT_SUCCESS
    }
    restore_failed = {
        record.undo_of_event_id
        for record in records
        if record.event_type == EVENT_UNDO and record.result == RESULT_FAILED
    }
    latest_batch_id = sort_records[-1].batch_id
    outstanding_latest = {
        record.event_id
        for record in sort_records
        if record.batch_id == latest_batch_id and record.event_id not in restored
    }
    latest_undoable = latest_batch_id if outstanding_latest else None

    grouped: dict[str, list[HistoryRecord]] = {}
    for record in sort_records:
        grouped.setdefault(record.batch_id, []).append(record)

    batches: list[HistoryBatch] = []
    for batch_id, batch_records in grouped.items():
        items = tuple(
            HistoryItem(
                event_id=record.event_id,
                source=Path(record.source_path),
                destination=Path(record.destination_path),
                item_type=ItemType(record.item_type),
                classification_time=_history_datetime(record.classification_time),
                restored=record.event_id in restored,
                restore_failed=(
                    record.event_id in restore_failed and record.event_id not in restored
                ),
            )
            for record in batch_records
        )
        batches.append(
            HistoryBatch(
                batch_id=batch_id,
                occurred_at=max(
                    _history_datetime(record.timestamp) for record in batch_records
                ).astimezone(),
                items=items,
                undoable=batch_id == latest_undoable,
            )
        )
    batches.sort(key=lambda batch: batch.occurred_at, reverse=True)
    return HistoryCalendar(tuple(batches), latest_undoable)
