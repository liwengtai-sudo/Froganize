"""Thin command-line adapter for Froganize / DropNest application services."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dropnest import __version__
from dropnest.exceptions import DropNestError
from dropnest.models import OperationStatus, PlanStatus
from dropnest.planner import build_plan
from dropnest.sorter import sort_workspace, undo_workspace
from dropnest.status import inspect_status
from dropnest.workspace import initialize_workspace

EXIT_SUCCESS = 0
EXIT_PARTIAL = 1
EXIT_FATAL = 2


def _local_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="dropnest",
        description=(
            "Froganize provides explicit, reversible monthly file-organization "
            "workflows."
        ),
        epilog=(
            "The web command assesses Desktop; preview, sort, status, and undo "
            "retain the compatibility WORKSPACE/Inbox flow."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show a Python traceback for development failures",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Froganize {__version__}",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser(
        "init",
        help="create or validate a Froganize workspace",
    )
    init_parser.add_argument("workspace", metavar="WORKSPACE")
    init_parser.add_argument(
        "--force-config",
        action="store_true",
        help="explicitly replace an existing configuration",
    )

    web_parser = commands.add_parser(
        "web",
        help="open the legacy local-only Desktop assessment dashboard",
        description=(
            "Use the compatibility web adapter to assess Desktop items and "
            "archive explicit selections."
        ),
        epilog="The server binds only to 127.0.0.1 and scans Desktop on demand.",
    )
    web_parser.add_argument("workspace", metavar="WORKSPACE")
    web_parser.add_argument(
        "--port",
        type=_local_port,
        default=8765,
        help="local port to use (default: 8765)",
    )
    web_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start the dashboard without opening a browser",
    )
    web_parser.add_argument(
        "--desktop",
        metavar="PATH",
        help=argparse.SUPPRESS,
    )

    for name, help_text in (
        ("preview", "show a read-only monthly move plan"),
        ("sort", "safely execute a fresh monthly move plan"),
        ("status", "inspect workspace state without changing it"),
        ("undo", "restore outstanding items from the latest sort batch"),
    ):
        command = commands.add_parser(
            name,
            help=help_text,
            description=help_text.capitalize() + ".",
            epilog="Only direct children of WORKSPACE/Inbox are processed.",
        )
        command.add_argument("workspace", metavar="WORKSPACE")
    return parser


def _print_plan(workspace: str) -> int:
    plan = build_plan(workspace)
    for entry in plan.entries:
        if entry.status is PlanStatus.PLANNED:
            rename = (
                f" (renamed from {entry.renamed_from})"
                if entry.renamed_from
                else ""
            )
            assert entry.target is not None
            assert entry.classification_time is not None
            print(
                f"PLAN  {entry.source} -> {entry.target} "
                f"[time: {entry.classification_time.isoformat()}]{rename}"
            )
        elif entry.status is PlanStatus.SKIPPED:
            print(f"SKIP  {entry.source} [{entry.reason}]")
        else:
            print(f"FAIL  {entry.source} [{entry.reason}]")
    print("Froganize preview.")
    print(f"Planned: {plan.count(PlanStatus.PLANNED)}")
    print(f"Skipped: {plan.count(PlanStatus.SKIPPED)}")
    print(f"Failed: {plan.count(PlanStatus.FAILED)}")
    return EXIT_PARTIAL if plan.count(PlanStatus.FAILED) else EXIT_SUCCESS


def _print_sort(workspace: str) -> int:
    plan, batch = sort_workspace(workspace)
    for result in batch.results:
        if result.status is OperationStatus.MOVED:
            print(f"MOVED {result.source} -> {result.target}")
        elif result.status is OperationStatus.SKIPPED:
            print(f"SKIP  {result.source} [{result.reason}]")
        else:
            print(f"FAIL  {result.source} [{result.reason}]")
    print("Froganize completed.")
    print(f"Moved: {batch.count(OperationStatus.MOVED)}")
    print(f"Skipped: {batch.count(OperationStatus.SKIPPED)}")
    print(f"Failed: {batch.count(OperationStatus.FAILED)}")
    print(f"Archive: {plan.workspace.timeline}")
    print(f"Batch ID: {batch.batch_id}")
    return EXIT_PARTIAL if batch.count(OperationStatus.FAILED) else EXIT_SUCCESS


def _print_undo(workspace: str) -> int:
    batch = undo_workspace(workspace)
    if batch.batch_id is None:
        print("Nothing to undo in the latest sort batch.")
        return EXIT_SUCCESS
    for result in batch.results:
        if result.status is OperationStatus.RESTORED:
            print(f"RESTORED {result.source} -> {result.target}")
        else:
            print(f"FAIL     {result.source} [{result.reason}]")
    print("Froganize undo completed.")
    print(f"Restored: {batch.count(OperationStatus.RESTORED)}")
    print(f"Failed: {batch.count(OperationStatus.FAILED)}")
    print(f"Undo batch ID: {batch.batch_id}")
    return EXIT_PARTIAL if batch.count(OperationStatus.FAILED) else EXIT_SUCCESS


def _print_status(workspace: str) -> int:
    report = inspect_status(workspace)
    print(f"Workspace: {report.workspace}")
    print(f"Valid: {'yes' if report.workspace_valid else 'no'}")
    print(f"Inbox items: {report.pending_count}")
    print(f"Sortable: {report.sortable_count}")
    print(f"Skipped: {report.skipped_count}")
    print(f"Failed to inspect: {report.failed_count}")
    print(f"Unreadable: {report.unreadable_count}")
    print(f"Archive months: {report.archive_month_count}")
    print(f"Latest sort batch: {report.latest_batch_id or 'none'}")
    print(f"Latest sort time: {report.latest_sort_time or 'none'}")
    print(f"Latest moved: {report.latest_moved_count}")
    print(f"Latest undo: {report.latest_undo_status}")
    print(f"Configuration valid: {'yes' if report.config_valid else 'no'}")
    print(f"History valid: {'yes' if report.history_valid else 'no'}")
    for problem in report.problems:
        print(f"Problem: {problem}")
    return EXIT_SUCCESS if report.workspace_valid else EXIT_PARTIAL


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "init":
        result = initialize_workspace(
            arguments.workspace,
            force_config=arguments.force_config,
        )
        print("Froganize workspace ready.")
        for path in result.created:
            print(f"Created: {path}")
        for path in result.preserved:
            print(f"Preserved: {path}")
        for path in result.updated:
            print(f"Updated: {path}")
        return EXIT_SUCCESS
    if arguments.command == "preview":
        return _print_plan(arguments.workspace)
    if arguments.command == "sort":
        return _print_sort(arguments.workspace)
    if arguments.command == "undo":
        return _print_undo(arguments.workspace)
    if arguments.command == "status":
        return _print_status(arguments.workspace)
    if arguments.command == "web":
        from dropnest.web import run_web

        run_web(
            arguments.workspace,
            desktop_path=arguments.desktop,
            port=arguments.port,
            open_browser=not arguments.no_browser,
            debug=arguments.debug,
        )
        return EXIT_SUCCESS
    raise AssertionError(f"Unhandled command: {arguments.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DropNest command-line interface with concise expected errors."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return _dispatch(arguments)
    except (DropNestError, OSError) as exc:
        if arguments.debug:
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FATAL


if __name__ == "__main__":
    raise SystemExit(main())
