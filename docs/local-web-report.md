# Froganize 0.2 Desktop Dashboard Report

> Historical implementation report. The native 0.3 main app no longer depends
> on this browser adapter; current architecture is documented in
> `FROGANIZE_MERGE_PLAN.md` and `docs/architecture.md`.

> Its seven-day groups and explicit-selection language are retained only as
> history. They do not describe the current one-click product contract.

Date: 2026-07-28 · mainline updated 2026-08-05

## Delivered outcome

Froganize no longer requires the user to move Desktop files into Inbox before
using the local dashboard. Opening `Froganize.app` now starts a local page that:

- assesses direct Desktop children;
- displays three primary age/safety outcomes;
- suggests safe projects after more than 7 completed days;
- starts with no selected items;
- keeps conservative cleanup recommendations collapsed and unchecked;
- allows any safe top-level item to be selected or cleared;
- moves only confirmed selections;
- restores the latest archive batch to Desktop.

Folders remain complete and are never partially selected.

## Evaluation behavior

- `recent`: 0–7 completed days, unchecked;
- `archive`: over 7 completed days, unchecked;
- `unsafe`: disabled and explained;
- `cleanup`: optional high-confidence temporary regular files inside More
  tools, unchecked.

Regular files use `st_mtime`. Folders use the newest descendant `st_mtime`.
Folder traversal reads metadata only, does not follow symbolic links, and
creates a deterministic tree fingerprint for execution-time revalidation.

## Web safety

- `127.0.0.1` bind only;
- loopback Host allowlist;
- random action token for all POST requests;
- 64 KiB request cap;
- no external assets or analytics;
- restrictive CSP and browser security headers;
- fixed server-owned Desktop and Timeline;
- exact current-assessment membership for Finder reveal;
- one-time assessment IDs for archive execution;
- text-node rendering of filesystem values.

## Filesystem safety

- Desktop and workspace cannot overlap.
- Only Desktop direct children are executable sources.
- DropNest’s own Desktop launcher is excluded.
- Whole folders become unsafe on unreadable or unsupported descendants.
- Nested symbolic links are not followed.
- More than 50,000 descendants causes a safe refusal.
- File snapshots and folder tree fingerprints are checked after confirmation.
- Targets are contained under Timeline and rechecked case-insensitively.
- Existing targets are never overwritten.
- History append failure rolls back the corresponding move.
- Undo never overwrites a Desktop conflict.

## Automated verification

The complete suite passes on the supported Python versions. The exact current
test count is intentionally reported by CI instead of being duplicated here.

New coverage includes:

1. three primary Desktop evaluation outcomes;
2. one-week boundary and default-empty selection;
3. direct-child-only presentation;
4. newest-descendant folder time;
5. launcher exclusion;
6. unreadable descendant refusal;
7. selected-only whole-item execution;
8. deep-change rejection after assessment;
9. Desktop history and undo;
10. operation without Inbox;
11. one-time web assessment capabilities;
12. fixed Desktop/Timeline open and current-item reveal;
13. invalid Host and token rejection;
14. conservative cleanup recommendations and guarded Trash execution.

## Browser verification

An isolated browser was connected to a temporary Desktop containing:

- one recent file;
- one 8–30 day file, now included in the archive suggestion;
- one old file;
- one old complete folder;
- one symbolic link.

Observed:

- primary group counts now reflect the three-outcome one-week model;
- no item is checked until the user selects it;
- the symbolic link disabled;
- no token placeholder leakage;
- no horizontal overflow at 1470px or 390px;
- archive of two selected items succeeded;
- latest-batch undo restored both items.

The browser test found a `<dialog>` compatibility issue: one Chromium build
closed a method-dialog without delivering the expected `close` event. The
confirmation button now invokes its callback explicitly, and the full
archive/undo flow passed afterward.

## App launcher

The macOS launcher:

- uses the transparent yellow Froganize mascot icon;
- starts the desktop-mode local service;
- replaces an older incompatible DropNest service only after verifying its
  project/workspace command;
- refuses to stop unrelated processes using port 8765;
- creates a Desktop shortcut only when no item already occupies that name;
- reuses a healthy desktop-mode service.

## Known limits

- The archive suggestion threshold is currently fixed at more than 7 completed
  days.
- Only the latest successful batch is undoable.
- The page shows metadata, not file previews.
- Very large folders are retained for manual review.
- The source launcher is portable: it stores the chosen workspace in the app
  bundle at installation time and resolves its own bundled project runtime.
- Public distribution still needs Apple signing, notarization, and a packaged
  runtime; the current launcher is a local developer installation.
- Legacy Inbox CLI code remains for compatibility but is not part of the daily
  Desktop flow.
