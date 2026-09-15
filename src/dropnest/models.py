"""Shared immutable models used by DropNest services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    """Resolved paths belonging to one fixed-layout DropNest workspace."""

    root: Path
    inbox: Path
    timeline: Path
    metadata: Path
    config: Path
    history: Path
    lock: Path


@dataclass(frozen=True, slots=True)
class InitResult:
    """Resources created and preserved by workspace initialization."""

    workspace: Workspace
    created: tuple[Path, ...]
    preserved: tuple[Path, ...]
    updated: tuple[Path, ...]


class ItemType(str, Enum):
    """Kinds of top-level Inbox items supported by the MVP."""

    FILE = "file"
    DIRECTORY = "directory"


class PlanStatus(str, Enum):
    """Planner decision for an Inbox item."""

    PLANNED = "planned"
    SKIPPED = "skipped"
    FAILED = "failed"


class PlanLayout(str, Enum):
    """Destination shape that the executor must independently enforce."""

    MONTHLY = "monthly"
    COLLECTION_BATCH = "collection_batch"


@dataclass(frozen=True, slots=True)
class ItemSnapshot:
    """Metadata used to detect source replacement or modification."""

    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    tree_digest: str | None = None


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One deterministic planner decision."""

    source: Path
    item_type: ItemType | None
    status: PlanStatus
    target_directory: Path | None = None
    target: Path | None = None
    classification_time: datetime | None = None
    year: int | None = None
    month: int | None = None
    snapshot: ItemSnapshot | None = None
    reason_code: str | None = None
    reason: str | None = None
    renamed_from: str | None = None


@dataclass(frozen=True, slots=True)
class SortPlan:
    """A read-only snapshot of planner output."""

    workspace: Workspace
    source_root: Path
    destination_root: Path
    layout: PlanLayout
    generated_at: datetime
    entries: tuple[PlanEntry, ...]

    def count(self, status: PlanStatus) -> int:
        """Count entries with a given planner status."""
        return sum(entry.status is status for entry in self.entries)


class EvaluationGroup(str, Enum):
    """Desktop activity group shown in the local dashboard."""

    RECENT = "recent"
    KEEP = "keep"
    ARCHIVE = "archive"
    CLEANUP = "cleanup"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class AssessmentEntry:
    """One top-level Desktop item and its user-facing evaluation."""

    plan_entry: PlanEntry
    group: EvaluationGroup
    age_days: int | None
    default_selected: bool


@dataclass(frozen=True, slots=True)
class DesktopAssessment:
    """Read-only evaluation of one Desktop snapshot."""

    plan: SortPlan
    entries: tuple[AssessmentEntry, ...]

    def count(self, group: EvaluationGroup) -> int:
        """Count entries in one activity group."""
        return sum(entry.group is group for entry in self.entries)


class OperationStatus(str, Enum):
    """Outcome of a requested move or restoration."""

    MOVED = "moved"
    TRASHED = "trashed"
    RESTORED = "restored"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome for one plan or undo entry."""

    source: Path
    target: Path | None
    status: OperationStatus
    reason_code: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Aggregate result of sort or undo."""

    batch_id: str | None
    results: tuple[OperationResult, ...]

    def count(self, status: OperationStatus) -> int:
        """Count outcomes with a given status."""
        return sum(result.status is status for result in self.results)


@dataclass(frozen=True, slots=True)
class HistoryItem:
    """One archived item projected for the read-only activity calendar."""

    event_id: str
    source: Path
    destination: Path
    item_type: ItemType
    classification_time: datetime
    restored: bool
    restore_failed: bool


@dataclass(frozen=True, slots=True)
class HistoryBatch:
    """One user-triggered organization batch shown on a calendar day."""

    batch_id: str
    occurred_at: datetime
    items: tuple[HistoryItem, ...]
    undoable: bool

    @property
    def restored_count(self) -> int:
        return sum(item.restored for item in self.items)

    @property
    def outstanding_count(self) -> int:
        return sum(not item.restored for item in self.items)


@dataclass(frozen=True, slots=True)
class HistoryCalendar:
    """Validated Desktop organization history ordered newest first."""

    batches: tuple[HistoryBatch, ...]
    latest_undoable_batch_id: str | None


@dataclass(frozen=True, slots=True)
class StatusReport:
    """Read-only summary of a DropNest workspace."""

    workspace: Path
    workspace_valid: bool
    pending_count: int
    sortable_count: int
    skipped_count: int
    failed_count: int
    unreadable_count: int
    archive_month_count: int
    latest_batch_id: str | None
    latest_sort_time: str | None
    latest_moved_count: int
    latest_undo_status: str
    config_valid: bool
    history_valid: bool
    problems: tuple[str, ...]
