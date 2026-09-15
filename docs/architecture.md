# Froganize 0.3 Unified Prototype Architecture

The public product is Froganize. `dropnest` remains the compatibility name for
the Python package, CLI entry point, local metadata directory, and filesystem
safety core.

## 0. Native one-click architecture

The native mainline removes assessment groups, per-item selection, and the
second confirmation from the primary path. Opening the app remains read-only;
clicking **收好桌面** is the single explicit mutation authorization:

```text
User clicks 收好桌面
    → desktop_app validates fixed Desktop + workspace
    → planner scans Desktop direct children and builds one immutable batch
    → planner excludes launchers, hidden/temp/incomplete, symlink and unsafe items
    → planner assigns each item its classification-time YYYY/YYYY-MM target
    → sorter revalidates the same plan and creates required month directories
    → sorter moves safe files and whole folders without replacement
    → history appends all successful operations under one shared batch ID
    → GUI shows moved/skipped/failed state, Open result, and Undo
```

There is no root-level timestamp batch directory. Each item enters
`Timeline/YYYY/YYYY-MM/` according to its own classification time. Regular files
use `st_mtime`; a whole folder uses the newest `st_mtime` in its readable tree
and still moves intact. Items from one click may therefore enter different
months while sharing one logical history batch ID for cross-month undo. A
workspace safety failure aborts before movement; item-level disappearance,
change, or failure is reported without corrupting independent successes.

Froganize's yellow frog and folder-shaped magic wand remain the visual language
for idle/checking/collecting/completed/partial-failure/undo states. They do not
add screens or decisions. Screenshot Intelligence stays in a secondary panel.
The existing Inbox CLI remains a compatibility interaction and shares the same
`Timeline/YYYY/YYYY-MM/` hierarchy. Assessment-oriented sections below describe
reusable or compatibility paths rather than the native primary interaction.

## 1. System shape

Froganize keeps the mature Python organizer core and Swift Screenshot
Intelligence agent in their existing languages. A narrow versioned JSON bridge
makes Python the deterministic authority for screenshot file mutations. The
self-contained macOS bundle contains all three executables:

```text
Froganize.app
├── Main app: macos_app.py -> Qt window
│   ├── complete Screenshot Intelligence control panel
│   │   └── JSON stdin -> fixed nested Swift binary --control
│   └── desktop_app.py
│       └── one click -> fresh Desktop plan -> checked execution
│           ├── monthly Timeline + shared history batch -> cross-month undo
│           └── macOS Trash (separate confirmed cleanup)
│
├── FroganizeFileOps
│   └── validate -> screenshot rename / rename undo -> activity.jsonl
│
└── nested Swift screenshot component (explicit opt-in)
    ├── same executable: control mode -> settings / Keychain / actions
    ├── enabled agent mode: screenshot detection -> Vision provider
    └── schema-v1 JSON stdin/stdout -> FroganizeFileOps

Compatibility only: dropnest CLI and loopback web adapter call the same Python
planner/executor services; neither is the native product entry point.
```

Qt widgets never implement filesystem policy. They call the framework-free
application service, which delegates every plan and mutation to the shared
safety core. The desktop bundle does not start HTTP, claim a port, or open a
browser. Screenshot AI is a separate, user-controlled network boundary; its
Swift component cannot rename or restore files directly. Opening its panel,
refreshing state, and saving local non-secret settings make no provider request.

### Static project website

`website/` is a separate, dependency-free marketing prototype. It contains
relative HTML/CSS assets only, makes no API requests, and has no access to the
workspace, Desktop, or Timeline. It may reuse synthetic screenshots and brand
illustrations, but it must never import organizer logic or present an
unverified public download. The old local dashboard remains under
`src/dropnest/web_assets/` only as a development/compatibility adapter.

## 2. Module map

### `cli.py`

Thin command adapter.

- Starts the legacy local Desktop dashboard when explicitly requested.
- Keeps legacy Inbox commands for compatibility.
- Converts expected failures to concise messages.
- Does not contain planning or move logic.

### `macos_app.py`

Self-contained macOS runtime host.

- Chooses or reuses the safe per-user workspace.
- Creates a fixed-path `DesktopApplication` service.
- Starts the native Qt event loop without a browser or local server.
- Reports expected startup failures without a traceback.
- Contains no planning or filesystem-move policy.

PyInstaller bundles this host, Qt, the Python runtime, package modules, and the
Froganize icon as an onedir `.app`. The build script performs a native-window
smoke test and then creates a DMG and checksum. Developer ID signing, hardened
runtime, notarization, and stapling remain a later public-release gate.

### `desktop_app.py`

Framework-free application use cases shared by presentation adapters.

- Fixes the validated workspace and Desktop paths once.
- Exposes one-click `collect_all`, which freshly plans every safe direct child
  and passes that exact plan to checked execution.
- Retains a short-lived immutable assessment session for compatibility selected
  archive and Trash actions, and claims it to prevent duplicate submission.
- Exposes only allowlisted Desktop/Timeline Finder operations.
- Delegates assessment, archive, Trash, status, and undo to the safety core.

### `gui.py`

Native PySide6 presentation layer.

- Uses Qt widgets, dialogs, and a background worker pool.
- Uses the visible assessment to explain what is movable or skipped while the
  one-click collection action remains dominant.
- Treats the collection click itself as authorization, without archive
  checkboxes or a second confirmation.
- Keeps optional Trash selection and confirmation separate.
- Shows concise results and refreshes after filesystem changes.
- Presents the complete Screenshot Intelligence panel: folder, consent,
  processing enablement, provider/model, Keychain credential actions,
  connection test, process-latest, rename undo, status, and recent activity.
- Sends typed control requests only to the fixed nested Swift executable (or an
  explicit development override); it does not open a second settings app.
- Contains no HTTP client, web view, or file-move policy.

### `intelligence_control.py`

Local process boundary between the Qt panel and the nested Swift component.

- Resolves the fixed packaged executable at
  `Contents/Library/LoginItems/FroganizeScreenshotAgent.app/Contents/MacOS/ScreenshotRenamer`.
- Invokes that same binary with `--control`, without a shell or another
  executable.
- Sends one bounded JSON request on stdin and parses one bounded JSON response.
- Passes a newly entered provider key only in stdin so Swift can write it to
  Keychain; the key is never placed in argv, the environment, logs, history, or
  the file-operation protocol, and is never echoed in a response.
- Treats timeouts, malformed responses, missing executables, and nonzero exits
  as concise, fail-closed panel errors.

### `intelligence_contract.py` and `agent_cli.py`

Bounded cross-language protocol boundary.

- Reads exactly one UTF-8 JSON request from stdin and writes one JSON response.
- Uses schema version 1, UUID request IDs, exact fields, duplicate-key rejection,
  and stable error codes.
- Supports configure-folder, rename-screenshot, and undo-rename actions.
- Accepts only a safe source basename and pre-AI file snapshot; AI never supplies
  a directory or destination path.
- Emits no traceback, secret, or image content on the protocol channel.

### `screenshot_operations.py`

Deterministic screenshot mutation authority.

- Validates the explicitly authorized screenshot root and direct-child source.
- Rejects symlinks, changed/disappeared sources, unsupported files, low
  confidence, unsafe AI fields, and path traversal.
- Sanitizes and bounds Unicode names, allocates case-insensitive collisions,
  and performs a no-replace rename.
- Uses an app-support mutation lock, write-ahead pending journal, append-only
  activity, rollback on history failure, and conservative crash recovery.
- Performs no provider request and never receives an API key.

### `intelligence_history.py` and `intelligence_status.py`

Private local state for screenshot rename/undo activity.

- Stores versioned non-secret configuration and append-only JSONL metadata under
  Application Support.
- Keeps screenshot bytes and credentials out of history.
- Exposes a read-only activity projection that does not create files or
  directories; the main panel combines it with non-secret Swift control state.

### `web.py`

Legacy loopback-only development adapter; it is not the desktop app entry.

- Fixes workspace and Desktop paths at server construction.
- Serves packaged HTML, CSS, and JavaScript.
- Enforces Host and action-token checks.
- Builds and caches one short-lived assessment.
- Accepts exact selected top-level names.
- Keeps archive and cleanup action allowlists separate.
- Exposes only Desktop, Timeline, and current-assessment reveal operations.

### `workspace.py`

Filesystem boundary validation.

- Resolves and validates managed workspace paths.
- Allows Desktop mode to operate without a physical Inbox.
- Validates the external Desktop source.
- Prevents Desktop/workspace/Timeline overlap.
- Owns the mutation lock.

### `planner.py`

Read-only domain planning.

- Keeps the legacy direct-Inbox planner.
- Scans direct Desktop children.
- Applies skip and placeholder rules.
- Computes file modification time.
- Computes whole-folder newest-descendant time.
- Creates metadata-only folder fingerprints.
- Assigns the three primary evaluation groups using the one-week threshold.
- Keeps a deliberately narrow cleanup classification for the collapsed
  More tools utility.
- Allocates case-insensitive conflict-safe targets.
- Does not create Timeline directories.

### `models.py`

Immutable data passed between layers:

- `Workspace`;
- `ItemSnapshot`;
- `PlanEntry`;
- `SortPlan`;
- `EvaluationGroup`;
- `AssessmentEntry`;
- `DesktopAssessment`;
- operation and status results.

### `conflict.py`

Pure target-name allocation:

- case-insensitive occupied-name set;
- extension preservation;
- compound-suffix preservation;
- deterministic `(1)`, `(2)`, … numbering.

### `sorter.py`

Checked filesystem mutation.

- Executes saved plans without destination recalculation.
- Filters a plan to explicit selected names.
- Revalidates the authorized source root.
- Rechecks file or complete folder snapshots.
- Creates safe Timeline year/month directories.
- Moves without replacement.
- Rolls back when history append fails.
- Restores the latest outstanding batch to its original source root.

### `cleanup.py`

Guarded, recoverable cleanup execution.

- Accepts only exact names in the saved cleanup recommendation set.
- Revalidates Desktop direct-child scope, regular-file type, symlink state,
  conservative cleanup rule, and metadata snapshot.
- Delegates to Finder to move items to macOS Trash.
- Never permanently deletes, empties Trash, or falls back to `rm`.
- Isolates failures so one item does not block the rest.

### `history.py`

Append-only event validation and querying.

- Strict JSONL parsing.
- Supports direct legacy Inbox and explicitly authorized Desktop sources.
- Validates source and destination relationships.
- Selects the latest successful sort batch for the active Inbox or Desktop
  source, preventing one compatibility flow from undoing the other.
- Tracks per-event undo completion.
- Never stores file content.

### `status.py`

Read-only health aggregation.

- Validates configuration and history.
- Counts archive months.
- Reports latest batch and undo state.
- Can inspect legacy Inbox or fixed Desktop context.

### `web_assets/`

No-framework browser UI.

- Three primary evaluation sections.
- Accessible top-level checkboxes.
- No default selection.
- Finder reveal controls.
- Confirmation dialog.
- One primary archive action, a collapsed separately confirmed Trash utility,
  and latest-batch undo.
- Responsive desktop/mobile layout.

## 3. Compatibility Desktop assessment flow

```text
Window opens or user chooses “重新检查”
    │
    ├─ validate archive workspace
    ├─ validate fixed Desktop
    ├─ list only Desktop direct children
    ├─ inspect each file/folder
    ├─ for folder: walk metadata without following links
    ├─ calculate classification time and tree digest
    ├─ allocate Timeline target
    ├─ assign recent / archive / unsafe for the primary flow
    ├─ classify narrow cleanup candidates for More tools
    └─ cache plan behind random assessment_id
```

Only one assessment is active. A new assessment replaces the previous one.

## 4. Compatibility selected archive flow

```text
User confirms selected top-level names
    │
    ├─ validate the selection collection
    ├─ atomically claim assessment_id
    ├─ reject duplicates, unknown names, unsafe entries
    ├─ filter saved SortPlan
    ├─ acquire workspace lock
    ├─ validate Desktop and Timeline again
    ├─ verify source snapshot/tree digest
    ├─ verify target is still free
    ├─ move one whole item
    └─ append history or roll back that item
```

The assessment ID is consumed before execution, preventing double submission.

## 5. Cleanup flow

```text
User separately confirms selected cleanup names
    │
    ├─ validate selection and the one-use assessment
    ├─ reject names outside the cleanup recommendation allowlist
    ├─ acquire the workspace mutation lock
    ├─ revalidate fixed Desktop and direct-child source
    ├─ reject symlinks, folders, changed snapshots, and rule changes
    ├─ ask Finder to move each selected file to macOS Trash
    └─ report per-item success or failure without permanent deletion
```

Trash is intentionally separate from archive history and undo. Finder owns
Trash placement and recovery; the dashboard tells the user to restore through
Finder rather than pretending it knows the final volume-specific Trash path.

## 6. Folder metadata algorithm

For a safe direct folder:

1. lstat the root folder;
2. traverse descendants with `os.scandir`;
3. sort names deterministically;
4. lstat each entry without following links;
5. retain the maximum `st_mtime_ns`;
6. hash relative path plus device, inode, mode, size, and mtime;
7. stop and mark unsafe on unreadable/unsupported/oversized trees.

The latest timestamp drives both evaluation and Timeline month. The digest
detects a deep change between assessment and execution.

A nested symbolic link contributes only its own metadata and is never entered.

## 7. Undo flow

```text
User confirms “撤销最近整理”
    │
    ├─ validate Desktop and workspace
    ├─ acquire workspace lock
    ├─ read strict history
    ├─ find latest successful sort batch
    ├─ remove already-restored events
    ├─ restore each item to original Desktop name
    ├─ reject conflicts/missing/type changes per item
    └─ append undo records
```

One failed item does not roll back successful restorations of other items.

## 8. Trust boundaries

### Presentation input

Untrusted:

- assessment ID;
- selected names;
- requested open/reveal action.

Controls:

- exact current-assessment name membership;
- action-specific archive/cleanup membership;
- no arbitrary path parameters.

The native window passes typed values directly to `desktop_app.py`. The legacy
web adapter additionally retains its loopback bind, Host allowlist, random POST
token, and request-size cap.

### AI and cross-process input

Untrusted:

- provider output;
- screenshot filename and filesystem snapshot;
- JSON request and response bytes;
- persisted Intelligence activity and pending journals.

Controls:

- explicit feature consent before screenshot upload;
- no provider request on panel open, status refresh, local setting save, key
  storage, or key removal;
- a real provider request only after an explicit connection test or while
  screenshot processing is explicitly enabled;
- screenshot-pattern, extension, regular-file, and no-symlink checks before
  upload;
- strict versioned schemas, bounded messages, exact fields, UUID request IDs,
  and response/request correlation;
- category and confidence allowlists plus Unicode filename sanitization;
- exact authorized root and direct-child validation;
- snapshot revalidation after AI returns;
- no-replace rename, request idempotency, journal recovery, and typed undo;
- API keys transiently pass from the main panel through local process memory and
  child-process stdin to the fixed Swift control entry, then reside in Keychain;
  they never enter argv, environment variables, logs, activity history,
  configuration files, or the Python file-operation contract.

### Filesystem metadata

Untrusted:

- names;
- symlinks;
- permissions;
- type changes;
- timestamps;
- target occupancy;
- history content.

Controls:

- lstat and resolved-parent checks;
- no symlink traversal;
- immutable snapshots;
- tree digest for folders;
- no-replace rename;
- case-insensitive conflict recheck;
- strict append-only history validation.

## 9. Planner/executor separation

Assessment must remain read-only and explain exact results. Execution must
consume that same decision snapshot. Combining them would make it impossible to
offer trustworthy checkboxes or to detect changes between review and movement.

The application service therefore stores a `DesktopAssessment`, then filters
its `SortPlan`; the GUI never calls a fresh “sort everything” operation.

## 9.1 Read-only organization calendar

`history.read_history` first validates the append-only JSONL stream and its path
boundaries. `history.project_history_calendar` then groups successful Desktop
sort events by batch and local operation day without touching the filesystem.
`DesktopApplication.history_calendar` exposes that immutable projection to the
native Qt calendar in `gui.py`.

The calendar never implements a second undo path. When the selected batch is the
latest outstanding batch, it delegates to `sorter.undo_workspace` and supplies
the expected batch ID. The executor acquires the workspace lock, rereads history,
and rejects a stale calendar selection before any restoration.

## 10. Legacy compatibility

The fixed workspace model still has an `Inbox` path and the original CLI planner
remains tested. Desktop web mode passes `require_inbox=False` and does not scan,
open, or restore to Inbox.

Existing Inbox data is never deleted during migration.

## 11. Unified bundle

`scripts/build_unified_macos_prototype.sh` builds:

```text
Froganize.app/Contents/
├── MacOS/Froganize
├── MacOS/FroganizeFileOps
└── Library/LoginItems/FroganizeScreenshotAgent.app/
    └── Contents/MacOS/ScreenshotRenamer
```

These are three execution roles: main Qt app, deterministic Python file helper,
and one nested Swift binary shared by background agent mode and `--control`
mode. The helper is frozen as a separate console executable. The nested
component is signed before the outer bundle, followed by strict deep signature
verification and a non-launching structure smoke test. This is an ad-hoc-signed
local prototype, not a notarized public release.

Maintainer-only rebuilds may instead set the explicit
`FROGANIZE_LOCAL_CODESIGN_IDENTITY` to a private certificate already installed
in the local Keychain. The unified builder signs every execution role from the
inside out without a trusted timestamp, rejects any resulting `cdhash`-bound
designated requirement, and fixes the nested component identifier before
accepting the build. This mode is deliberately separate from Developer ID and
cannot be combined with notarization. Creation of the private local identity is
never part of a build and requires a separately confirmed setup script.

## 12. Future extension seams

- Configurable age thresholds belong in versioned config and evaluation policy.
- “Always keep on Desktop” belongs in a separate explicit rule store.
- Native macOS UI can call the same assessment/selection services.
- Screenshot monitoring remains limited to the opt-in screenshot feature. Any
  future general Desktop watcher may emit assessment suggestions only and must
  not bypass explicit selection and execution safeguards.
- Screenshot activity is intentionally separate from workspace archive history
  in 0.3; a future unified activity view can project both typed event streams
  without merging their mutation semantics.
