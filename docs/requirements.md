# Froganize 0.3 Unified Prototype Requirements

Froganize is the public product and mascot name. The existing `dropnest`
Python package, command, configuration directory, and archive history schema
remain stable compatibility interfaces in version 0.3.

## 0. Native-product mainline

This section is authoritative for the implemented native UI and supersedes the
legacy assessment/selection workflow below where they conflict. Later sections
continue to document reusable core behavior and compatibility adapters.

The primary window has one dominant action: **Collect Desktop** (`收好桌面`).
Opening the app is read-only; clicking this button is explicit authorization
for one run, without checkboxes or a second confirmation. One run must:

- inspect only direct children of the fixed Desktop;
- move every safely movable regular file and whole folder as one batch;
- never split folders or expose nested children as separate choices;
- place each item in `Timeline/YYYY/YYYY-MM/` using its own classification
  time, without creating a root-level timestamp batch folder;
- skip Froganize/current and known old launchers, hidden items, temporary
  files, incomplete downloads, symlinks, reliable cloud placeholders,
  unreadable items, unsupported types, and anything else unsafe;
- report moved, skipped, and failed items with reasons;
- append successful moves to history and make the latest batch undoable
  without overwriting Desktop conflicts.

Planning and execution remain separate internally and consume the same plan.
Sources and targets are revalidated immediately before movement. The yellow
frog and folder-shaped magic wand remain the brand and operation-state language,
not extra workflow. Screenshot Intelligence remains a secondary feature.

The native action and legacy `dropnest` Inbox CLI share the
`Timeline/YYYY/YYYY-MM/` layout. They differ in source and interaction, not in
the archive hierarchy.

## Compatibility web-adapter requirements

Sections 1 onward preserve the earlier browser adapter's selection contract for
regression testing. They are not requirements for the native one-click screen.

## 1. Product problem (compatibility context)

The user’s actual problem is Desktop visual clutter, not the absence of another
intake folder. Requiring a manual Desktop → Inbox → Timeline flow adds friction
without helping the user decide what should leave the Desktop.

DropNest should make Desktop cleanup understandable, selective, reversible, and
safe:

```text
Desktop -> assess -> user selects -> Timeline
```

## 2. User-visible locations

The primary workflow exposes only:

- `~/Desktop`: active work surface and fixed source;
- `WORKSPACE/Timeline`: stable archive destination.

`.dropnest` remains internal metadata. A legacy Inbox may remain in an existing
workspace for compatibility, but the Desktop dashboard must not require it.

## 3. Launch experience

The user opens `Froganize.app` as a standalone native PySide6 window. It does
not require a browser, local URL, or TCP port. The optional Screenshot
Intelligence component is opened from the main app or menu bar and remains a
lightweight Swift agent.

Opening the window automatically performs a read-only Desktop assessment. It must
never move an item merely because the application was opened.

## 4. Assessment scope

- Inspect only direct children of the fixed Desktop path.
- Present each direct file as one item.
- Present each direct folder as one item.
- Never expose nested children as independently selectable items.
- Never split a selected folder.
- Exclude the DropNest Desktop launcher itself.

## 5. One-week mainline and three visible groups

Use the selected item’s classification time relative to assessment time:

| Group | Rule | Default |
| --- | --- | --- |
| `recent` | 0–7 completed days since modification | unchecked |
| `archive` | more than 7 completed days | unchecked |
| `unsafe` | cannot be safely and completely evaluated | disabled |

Users may manually select any safe item regardless of its recommendation.
Unsafe items remain on Desktop and display a reason.

The user-facing labels are **Keep on Desktop**, **Suggested archive**, and
**Leave untouched**. No item is selected automatically.

Cleanup remains an optional, collapsed **More tools** utility rather than a
fourth part of the primary flow. It may recommend only regular
files matching `.DS_Store`, a `~` name prefix, or the suffixes `.tmp`,
`.download`, `.crdownload`, and `.part`. Folders, arbitrary hidden files,
symbolic links, and cloud placeholders are never cleanup recommendations.

## 6. File classification time

For a regular file, use `st_mtime`.

The dashboard must show:

- item name;
- file or whole-folder type;
- age in completed days;
- exact classification time;
- planned destination;
- conflict rename when applicable.

## 7. Folder classification time

A top-level folder moves as one intact tree. Its classification time is the
latest `st_mtime` among:

- the top-level folder;
- every readable descendant file;
- every readable descendant directory;
- a nested symbolic link’s own metadata, without following its target.

The scan reads metadata only. It must not read file contents.

The whole folder becomes unsafe when:

- a descendant cannot be listed or inspected;
- a reliable cloud placeholder is found;
- an unsupported filesystem item is found;
- the metadata scan exceeds 50,000 descendants.

## 8. Selection and confirmation

Each safe row has a checkbox. Every item starts unchecked.

The page supports:

- select or clear a complete group;
- clear the primary archive selection;
- reveal a current assessed item in Finder;
- reassess Desktop;
- preview the exact Timeline target;
- archive selected items through the primary action;
- optionally expand More tools and move explicitly selected cleanup
  recommendations to macOS Trash;
- undo the latest successful archive batch.

Archiving requires a confirmation dialog listing selected top-level names.
Trash uses a separate selection and confirmation. Cleanup items always start
unchecked and can be restored through Finder Trash; Froganize does not provide
permanent deletion or empty-Trash controls.

## 9. Deterministic selected execution

Assessment and execution must use the same saved plan:

- the server issues a random, short-lived assessment ID;
- archive requests must provide that ID and exact selected top-level names;
- an assessment can be executed at most once;
- unknown, duplicate, nested, or unsafe names are rejected;
- execution must not recalculate destinations silently.

If an item changes after assessment, that item fails without moving.

For folders, the metadata-only tree fingerprint must also match, so a nested
change invalidates the planned whole-folder move.

Cleanup requests use the same one-use assessment capability. The server accepts
only exact names already classified as `cleanup`, rechecks direct-child scope,
regular-file type, symlink status, conservative rule membership, and snapshot,
then asks Finder to move each item to Trash. One failure does not block the
remaining selected items.

## 10. Archive layout and conflicts

Selected items move to:

```text
Timeline/YYYY/YYYY-MM/
```

The year and month come from the same classification time shown in the
assessment.

No existing file or folder may be overwritten. Conflict names are allocated
case-insensitively:

```text
report (1).pdf
archive (1).tar.gz
Project (1)
```

The target is checked again immediately before moving.

## 11. History and undo

Every successful Desktop → Timeline move appends one JSONL record containing:

- event and batch IDs;
- timestamp;
- original Desktop path;
- Timeline destination;
- item type;
- classification time;
- result.

No file content is recorded.

Undo restores outstanding items from the latest successful archive batch to
their original direct Desktop paths. Undo:

- never overwrites a Desktop conflict;
- reports missing Timeline targets;
- records success or failure in history;
- continues safely when another item fails;
- can be retried for outstanding failures.

## 12. Fixed path safety

- The native application fixes the Desktop path at startup; widgets cannot
  provide another source.
- Desktop and workspace must be resolved absolute directories.
- Neither may contain the other.
- Timeline cannot be inside Desktop.
- Desktop cannot be `/` or the user home directory.
- Desktop and managed directories cannot be symbolic links.
- Sources must be direct Desktop children.
- Targets must remain under Timeline.
- Nested symbolic links are never followed.
- The interface can open only fixed Desktop and Timeline paths.
- Reveal accepts only names in the current assessment.

## 13. Native interface and legacy local web security

- The shipped macOS application uses native Qt widgets and calls the
  framework-free application service directly.
- It must not embed a web view, start an HTTP server, claim a port, or open a
  browser.
- Assessment and mutation run away from the GUI thread so the window remains
  responsive.
- The optional legacy development dashboard retains these additional controls:

- Bind only to `127.0.0.1`.
- Reject non-loopback Host headers.
- Require a random action token for every POST.
- Limit request size.
- Serve no external scripts, fonts, analytics, or images.
- Use restrictive CSP, frame denial, no-referrer, no-store, and nosniff headers.
- Render filesystem values through text nodes, not HTML injection.

## 14. Status

The dashboard reports:

- workspace/config/history validity;
- Desktop and Timeline paths;
- five assessment counts;
- Timeline month count;
- latest successful archive batch;
- latest undo state;
- clear user-facing problems.

The main window also exposes a read-only Screenshot Intelligence projection:
configured screenshot folder, latest successful rename and time, outstanding
rename-undo count, and state errors. This projection must not claim that the
background agent is running when that fact is not known.

## 15. Screenshot Intelligence

- The feature is off by default and requires explicit consent before upload.
- It processes only supported macOS system screenshot filename patterns and
  image extensions in the explicitly authorized folder.
- Symbolic links and non-regular files are rejected before upload.
- Swift keeps screenshot detection, provider calls, Keychain access, and
  lightweight menu-bar controls.
- Python owns configure-folder, rename, activity persistence, and rename undo
  through versioned JSON over stdin/stdout.
- AI may provide title, summary, category, confidence, and sensitivity only. It
  may not provide a source directory, destination path, or mutation command.
- The helper must revalidate the pre-AI file snapshot, sanitize and bound the
  Unicode filename, handle collisions case-insensitively, and never overwrite.
- Missing keys, network/provider errors, invalid responses, helper failures,
  changed/disappeared sources, duplicates, or crashes must fail safely without
  losing the original file.
- Screenshot rename/undo activity is stored locally without screenshot bytes or
  credentials. In 0.3 it remains a typed activity stream separate from archive
  history while being visible from the main app.

## 15.1 Organization calendar

- The native app projects validated Desktop sort history into calendar days
  using each operation timestamp in the user's local timezone.
- A marked day shows its batches, original item names, Timeline destinations,
  and whether each item remains archived, was restored, or had a failed restore.
- Calendar browsing is read-only and must never create directories, move files,
  or repair damaged history silently.
- Older batches remain visible but cannot be undone. Only the outstanding latest
  Desktop batch may be offered because that is the executor's safe undo contract.
- Calendar undo must pass the expected batch ID into the locked executor. If
  history changed after the view loaded, the operation stops before moving files.
- Damaged, incomplete, unreadable, or unsafe history disables calendar undo and
  produces a concise user-facing error.

## 16. Non-goals

This phase does not implement:

- general-purpose background Desktop monitoring;
- automatic movement on application launch;
- recursive partial folder selection;
- file content preview;
- AI classification of ordinary files, PDFs, Office documents, folders, or
  videos;
- permanent deletion, emptying Trash, arbitrary deletion, or duplicate cleanup;
- a Froganize server, cloud sync, accounts, database, embeddings, vector search,
  or RAG;
- arbitrary browser-provided source paths;
- App Store distribution or a hosted download website.

## 17. Acceptance criteria

- The native main window exposes one dominant `收好桌面` action;
  clicking it collects all and only safe Desktop direct children into their
  classification-time `Timeline/YYYY/YYYY-MM/` directories without another
  confirmation or a root-level timestamp batch directory.
- Launcher, hidden, temporary, incomplete-download, symlink, placeholder,
  unreadable, unsupported, and otherwise unsafe entries stay put with reasons.
- One click shares a history batch ID across every moved item, including items
  placed in different months; that logical batch never overwrites and can be
  undone safely as one operation.
- The mascot communicates operation state without adding interaction steps;
  Screenshot Intelligence remains secondary, and native collection plus the
  legacy CLI share the monthly Timeline hierarchy.
- Assessment-based criteria below apply only to retained compatibility adapters,
  not the native one-click mainline.
- Opening the Desktop app automatically shows a read-only assessment with three
  primary outcomes and a collapsed optional cleanup utility.
- Only direct Desktop children appear.
- Items modified within the last 7 completed days are kept on Desktop.
- Safe items older than 7 completed days are suggested for archive.
- Every assessment starts with no selected items.
- Unsafe items are disabled and explained.
- Cleanup recommendations are conservative, unchecked, and separately confirmed.
- Confirmed cleanup items move to recoverable macOS Trash, never permanent deletion.
- Folders use newest descendant modification time and move intact.
- Only explicitly selected items move.
- Assessment destinations match execution.
- Nested changes after assessment block the folder move.
- Conflicts never overwrite.
- Successful moves write history.
- Latest Desktop batch can be safely undone.
- Desktop mode works without an Inbox directory.
- No tests access the user’s real Desktop.
- The package installs in a fresh virtual environment.
- The self-contained macOS bundle runs without the checkout or `.venv`.
- Screenshot Intelligence is disabled until explicit consent.
- The Swift agent reaches the deterministic helper through the versioned JSON
  contract and has no direct rename fallback.
- The helper safely handles invalid AI output, Unicode/long/colliding names,
  duplicate requests, missing/changed files, history failure, crash recovery,
  and rename undo.
- The unified bundle contains the main app, helper, and nested agent at fixed
  validated paths.
- The complete automated suite passes.
