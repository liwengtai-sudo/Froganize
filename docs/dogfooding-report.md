# Controlled dogfooding report

Date: 2026-07-19

Environment: macOS 15.6.1, arm64, Python 3.13.12

## Purpose

This stage exercised the installed `dropnest` console script through the full
MVP workflow using only a pytest temporary directory. It did not scan, create,
or move files in the real Desktop, Downloads, Documents root, home directory,
or any unrelated project.

The executable scenario is kept in `tests/test_acceptance.py` so every future
change must preserve the same product-level behavior.

## Scenario

One workspace path contained spaces and one Inbox contained:

| Item | Classification | Expected result |
| --- | --- | --- |
| `report.pdf` | May 2026 | Move to `2026/2026-05` |
| `screenshot.png` | June 2026 | Move to `2026/2026-06` |
| `research-data.tar.gz` | July 2026 | Preserve compound suffix and rename around an existing target |
| `Old Project/` | November 2025 | Move the complete nested folder intact |
| `.DS_Store` | Hidden | Skip with reason |
| `~draft.docx` | Temporary name | Skip with reason |
| `transfer.tmp` | Temporary suffix | Skip with reason |
| `photo.jpg.icloud` | Reliable iCloud placeholder form | Skip with reason |
| `external-link` | Symbolic link | Skip without following |

The occupied `research-data.tar.gz` target and a symlink target outside the
workspace both remained unchanged.

## Verified workflow

1. `dropnest init` created the fixed workspace.
2. `dropnest preview` reported 4 planned, 5 skipped, and 0 failed.
3. A complete before/after tree snapshot proved preview had no side effects.
4. `dropnest sort` moved 4 and skipped 5.
5. Files landed in four expected year/month directories.
6. The compound conflict became `research-data (1).tar.gz`.
7. The project folder retained its nested `src/main.py`.
8. Four sort records contained metadata but no fixture payloads.
9. `dropnest status` reported a valid workspace, 5 remaining skipped Inbox
   items, 4 archive months, and 4 latest moves.
10. `dropnest undo` restored all 4 moved items without changing the pre-existing
    archive target.
11. A repeated undo reported nothing outstanding and did not reach an older
    batch.
12. History ended with 4 sort and 4 successful undo records.

## Historical results

These counts record the 2026-07-19 MVP baseline. The suite has grown since this
run; use the current CI result for the release status.

```text
tests/test_acceptance.py: 1 passed
complete suite: 96 passed
clean verification environment: 96 passed
```

No product or safety defect was found in this controlled scenario.

## Observations

- Undo intentionally leaves empty year/month directories in Timeline. Removing
  directories would add deletion semantics and ownership ambiguity, so it
  remains outside the MVP.
- The current planner is deterministic for a stable filesystem snapshot, and
  the real CLI output exposes every skip and conflict decision.
- Absolute paths in history make workspace relocation unsupported after a sort.
- The next product phase—automatic monitoring—must solve file-copy completion
  detection before invoking this existing planner and executor. A raw create
  event is not sufficient evidence that a large file or folder is ready.

## Gate for automatic monitoring

Before implementing a watcher, define and test:

- how an item is considered stable and fully copied;
- event debounce/coalescing behavior;
- what happens while a user is still writing a folder;
- how watcher actions acquire the existing workspace lock;
- whether automatic execution requires a configurable delay or remains
  preview-only by default;
- restart behavior for events observed immediately before a crash.

The watcher must call the same workspace validator, planner, executor, history,
and lock services. It must not introduce a second sorting implementation.
