"""Application-specific exceptions for DropNest."""

from __future__ import annotations


class DropNestError(Exception):
    """Base class for expected, user-facing DropNest failures."""


class WorkspaceError(DropNestError):
    """The requested workspace is missing or invalid."""


class WorkspaceSafetyError(WorkspaceError):
    """A workspace path violates a safety invariant."""


class ConfigurationError(WorkspaceError):
    """The workspace configuration is missing, corrupt, or unsupported."""


class WorkspaceLockError(WorkspaceError):
    """A mutating operation could not acquire the workspace lock."""


class PlanningError(DropNestError):
    """A safe move plan could not be produced."""


class HistoryError(DropNestError):
    """History could not be written or safely interpreted."""
