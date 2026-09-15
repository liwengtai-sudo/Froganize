#!/usr/bin/env python3
"""Fail closed when a prospective public repository contains local data.

The check examines files Git would consider for a commit: tracked files plus
untracked, non-ignored files.  It never follows symlinks and never reads paths
outside the repository root.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


MAX_PUBLIC_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_USER_PLACEHOLDERS = {
    "example",
    "name",
    "username",
    "your-name",
    "your_name",
}
FORBIDDEN_NAMES = {
    ".env",
    ".env.local",
    "history.jsonl",
    "workspace.lock",
}
FORBIDDEN_SUFFIXES = {".key", ".p8", ".p12", ".pem"}
FORBIDDEN_PARTS = {
    ".dropnest",
    ".pytest_cache",
    ".venv",
    ".venv-release",
    "__pycache__",
    "build",
    "dist",
}

PATH_BOUNDARY = r"(?<![A-Za-z0-9._-])"
MAC_HOME = re.compile(PATH_BOUNDARY + "/" + r"Users/([^/\s\"'`]+)")
LINUX_HOME = re.compile(PATH_BOUNDARY + "/" + r"home/([^/\s\"'`]+)")
WINDOWS_HOME = re.compile(r"[A-Za-z]:\\\\Users\\\\([^\\\s\"'`]+)")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKID[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


def _git_candidates(root: Path) -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    relative_paths = (
        Path(value.decode("utf-8"))
        for value in completed.stdout.split(b"\0")
        if value
    )
    return tuple(root / relative for relative in relative_paths)


def _is_placeholder_home(match: re.Match[str]) -> bool:
    return match.group(1).casefold() in ALLOWED_USER_PLACEHOLDERS


def scan_paths(root: Path, paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Return concise findings without exposing file contents."""
    resolved_root = root.resolve()
    findings: list[str] = []
    for candidate in sorted(paths, key=lambda path: str(path)):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            findings.append(f"outside repository: {candidate}")
            continue
        if candidate.is_symlink():
            findings.append(f"symlink is not allowed in public candidate: {relative}")
            continue
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            findings.append(f"resolved outside repository: {relative}")
            continue
        if any(part in FORBIDDEN_PARTS or part.endswith(".egg-info") for part in relative.parts):
            findings.append(f"local/generated path: {relative}")
            continue
        if candidate.name in FORBIDDEN_NAMES or candidate.suffix.casefold() in FORBIDDEN_SUFFIXES:
            findings.append(f"credential or local-state filename: {relative}")
            continue
        if not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            findings.append(f"unreadable candidate: {relative}")
            continue
        if size > MAX_PUBLIC_FILE_BYTES:
            findings.append(f"file exceeds 10 MiB review limit: {relative}")
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError:
            findings.append(f"unreadable candidate: {relative}")
            continue
        for pattern in (MAC_HOME, LINUX_HOME, WINDOWS_HOME):
            if any(not _is_placeholder_home(match) for match in pattern.finditer(text)):
                findings.append(f"personal absolute path: {relative}")
                break
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            findings.append(f"possible live credential: {relative}")
    return tuple(findings)


def scan_history_text(text: str) -> tuple[str, ...]:
    """Inspect Git patch text without returning matched content."""
    findings: list[str] = []
    for pattern in (MAC_HOME, LINUX_HOME, WINDOWS_HOME):
        if any(not _is_placeholder_home(match) for match in pattern.finditer(text)):
            findings.append("Git history contains a personal absolute path")
            break
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        findings.append("Git history contains a possible live credential")
    return tuple(findings)


def scan_git_history(root: Path) -> tuple[str, ...]:
    """Scan committed patches so deleting a secret later cannot hide it."""
    completed = subprocess.run(
        ["git", "log", "-p", "--all", "--no-color", "--no-ext-diff"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return scan_history_text(completed.stdout.decode("utf-8", errors="replace"))


def scan_repository(
    root: Path,
    *,
    include_history: bool = True,
) -> tuple[str, ...]:
    findings = list(scan_paths(root, _git_candidates(root)))
    if include_history:
        findings.extend(scan_git_history(root))
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check tracked and unignored files before publishing Froganize."
    )
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--working-tree-only",
        action="store_true",
        help="skip committed history (diagnostics only; unsafe for publication)",
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        findings = scan_repository(
            root,
            include_history=not args.working_tree_only,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Public repository preflight could not run: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("Public repository preflight failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Public repository preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
