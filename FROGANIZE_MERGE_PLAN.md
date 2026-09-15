# Froganize 0.3 Unified Prototype — Integration Record

> Status: implemented local prototype
> Date: 2026-08-13
> Scope: connect the existing Python/PySide6 organizer and Swift/SwiftUI
> screenshot prototype without a full rewrite.

> Historical integration record: the current organizer mainline supersedes the
> selection and one-week recommendation language below with one explicit
> **Collect Desktop** action. The complete Swift source has since moved into
> `swift/ScreenshotIntelligence/` so the unified build no longer depends on a
> sibling checkout.

## Outcome

Froganize 0.3 now has one runnable product path:

```text
Screenshot
→ Understand
→ Rename
→ Desktop
→ Organize
→ User Confirmation
→ Timeline
```

The two mature implementations remain in their existing languages. A small,
versioned JSON contract makes Python the only authority that may rename or undo
a screenshot. The Swift component detects screenshots and calls the configured
Vision provider. The main Python app keeps Desktop assessment, user
confirmation, Timeline archive, archive undo, and a complete Screenshot
Intelligence control panel.

## Original projects

### Froganize organizer

Repository root: this repository.

```text
Froganize.app
→ macos_app.py
→ gui.py
→ desktop_app.py
→ planner.py / sorter.py / cleanup.py
→ history.py / workspace.py / conflict.py
→ Desktop / Timeline / macOS Trash
```

Stable behavior retained:

- Desktop direct-child assessment;
- metadata-only file and whole-folder planning;
- explicit selection and confirmation;
- one-week archive recommendation;
- deterministic monthly Timeline target;
- case-insensitive collision handling without overwrite;
- changed-source detection;
- append-only archive history and latest-batch undo;
- native PySide6 UI and compatibility CLI/web adapters.

### AI Screenshot Renamer

Source now lives in `swift/ScreenshotIntelligence/` in this repository.

Stable behavior retained:

- macOS screenshot filename detection;
- serial folder-watcher orchestration;
- image preprocessing;
- OpenAI-compatible provider clients;
- Keychain credentials;
- menu-bar settings and feedback.

Direct Swift file mutation and its legacy authoritative history were removed
from the production flow.

## Chosen integration architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ Froganize.app                                               │
│                                                             │
│  Main app (Python + PySide6)                                │
│  ├── Desktop assessment / confirmation                      │
│  ├── Timeline archive / archive undo                        │
│  └── complete Screenshot Intelligence control panel          │
│                         │ JSON stdin + --control             │
│                         ▼                                   │
│                                                             │
│  Screenshot component (one Swift executable)                │
│  ├── control mode: settings / Keychain / explicit actions   │
│  ├── enabled mode: screenshot detection / provider request  │
│  └── JSON request via stdin/stdout                           │
│                         │                                   │
│                         ▼                                   │
│  FroganizeFileOps (frozen Python helper)                    │
│  ├── strict contract validation                             │
│  ├── deterministic rename / undo                            │
│  └── activity, idempotency, rollback, recovery              │
└─────────────────────────────────────────────────────────────┘
```

Why this design:

1. It reuses both working prototypes instead of introducing a risky rewrite.
2. A one-request subprocess has no permanent port, server, authentication
   surface, or command queue.
3. JSON is easy to validate and test in both languages.
4. Swift retains the native menu-bar, watcher, provider, and Keychain strengths.
5. Python reuses the mature no-overwrite filesystem safety model.
6. A helper failure can fail closed; there is no unsafe direct-rename fallback.

## Integration contract

Transport:

- one UTF-8 JSON request on stdin;
- one UTF-8 JSON response on stdout;
- no shell invocation;
- schema version `1`;
- maximum request and response sizes;
- UUID request correlation.

Actions:

```text
configure_screenshot_root
rename_screenshot
undo_screenshot_rename
```

The rename request contains only:

- a safe source basename, never a directory or target path;
- the file snapshot captured before the provider request;
- AI semantic output: title, summary, category, confidence, sensitive;
- non-secret provider and model identifiers;
- schema version and request ID.

Responses are typed as configured, renamed, undone, skipped, or error. Expected
errors carry stable codes and concise messages. Python does not emit tracebacks
or secrets over stdout.

## Screenshot rename flow

```text
Folder event
→ Swift verifies supported screenshot name and regular non-symlink image
→ Swift captures lstat snapshot
→ explicit consent check
→ selected provider returns strict semantic analysis
→ Swift sends contract request to fixed helper
→ Python validates configured root and exact direct child
→ Python rechecks the pre-AI snapshot
→ Python sanitizes and bounds the proposed Unicode name
→ Python allocates a case-insensitive collision-safe name
→ pending journal is written
→ atomic no-replace rename
→ append and fsync activity record
→ remove pending journal
→ return validated response
```

If the provider, network, response, helper, source, history, or target is unsafe,
the operation skips or fails without an overwrite. A normal history-write error
rolls the rename back. A pending journal allows conservative recovery after an
abrupt interruption.

## Rename undo flow

Undo accepts either an exact rename event ID or the latest outstanding rename.
The helper:

- reads strict activity;
- confirms the event belongs to the configured screenshot root;
- confirms the renamed source still matches its recorded snapshot;
- refuses to overwrite an occupied original name;
- performs an atomic no-replace restore;
- appends a typed undo event;
- rolls back if the undo event cannot be made durable.

Screenshot rename history remains separate from workspace archive history in
0.3. Their event types and undo semantics are different. The main app projects
a small screenshot status summary rather than pretending the streams are one.

## Main app integration

The native sidebar now includes the complete Screenshot Intelligence panel:

- screenshot folder and upload consent;
- intelligent naming enable/disable;
- provider and model;
- API-key save/remove through Keychain;
- explicit connection test and process-latest actions;
- latest status and recent activity;
- latest screenshot-rename undo.

The panel controls the existing nested Swift executable instead of opening a
second settings application. Packaged lookup is fixed to:

```text
Froganize.app/Contents/Library/LoginItems/
  FroganizeScreenshotAgent.app/Contents/MacOS/ScreenshotRenamer --control
```

Each action uses a bounded JSON stdin/stdout exchange without a shell. The same
binary retains its enabled background-agent role; no fourth executable is
added. Development may use an explicit absolute environment override. No
arbitrary executable path comes from normal UI input.

## Privacy decisions

Normal Desktop organization:

- reads filesystem metadata only;
- does not upload ordinary file contents;
- makes no provider request.

Screenshot Intelligence:

- defaults off;
- requires explicit user enablement;
- processes only supported system screenshot patterns in the authorized folder;
- skips symlinks before upload;
- uploads only the matched screenshot to the selected provider;
- sends a key entered in the main panel only through local process memory and
  child-process stdin to the fixed Swift control entry, then stores it in macOS
  Keychain;
- never includes API keys in argv, environment variables, stdout/stderr, logs,
  activity history, configuration files, the Python file-operation contract,
  or the repository;
- records metadata and semantic output, never screenshot bytes.

Opening or refreshing the panel and saving local non-secret settings do not
contact a provider. A live provider request is permitted only after the user
clicks the connection test or explicitly enables screenshot processing. Normal
Desktop assessment and organization remain metadata-only and local in either
case.

Sensitive content cannot be detected until a provider has seen an uploaded
screenshot. The interface therefore discloses the upload before consent rather
than implying that the sensitivity flag prevents upload.

## File safety decisions

- AI never receives filesystem mutation authority.
- Source roots must be explicit absolute real directories, not `/`, home, a
  symlink, Froganize state, or a known workspace overlap.
- Only a configured root's direct regular-file child can be renamed.
- `..`, separators, NUL, unsafe categories, malformed Unicode, long fields, and
  duplicate JSON keys are rejected.
- The exact device, inode, mode, size, and nanosecond mtime are rechecked after
  AI analysis.
- Filenames are normalized, sanitized, UTF-8 byte bounded, and extension
  controlled by the original supported image.
- Collision checks are case-insensitive and execution uses atomic no-replace.
- `request_id` plus request fingerprint provides idempotency.
- Pending journal recovery refuses records outside the currently authorized
  root, including tampered journals.
- Archive and Inbox histories are now source-scoped so one flow cannot undo the
  other's latest batch.
- Arbitrary hidden `.tmp` files remain unsafe instead of being promoted to the
  cleanup tool.

## Implemented files

Python integration:

- `src/dropnest/intelligence_contract.py`
- `src/dropnest/agent_cli.py`
- `src/dropnest/intelligence_history.py`
- `src/dropnest/intelligence_status.py`
- `src/dropnest/screenshot_operations.py`
- `tests/test_screenshot_intelligence.py`
- `froganize-fileops` console entry in `pyproject.toml`

Main-app integration and regressions:

- `src/dropnest/gui.py`
- `src/dropnest/history.py`
- `src/dropnest/planner.py`
- `src/dropnest/sorter.py`
- `src/dropnest/status.py`
- corresponding GUI, cleanup, Desktop, and history tests

Swift integration in `swift/ScreenshotIntelligence/`:

- `FileOperationBroker.swift`
- updated `AppModel`, settings, credentials, watcher, app identity, provider
  client, self-test, build script, plist, and README

Unified packaging:

- `scripts/froganize_fileops_entry.py`
- `scripts/build_unified_macos_prototype.sh`
- `scripts/smoke_unified_macos_bundle.py`
- `tests/test_unified_macos_packaging.py`

## Unified package layout

```text
dist/unified/Froganize.app/Contents/
├── MacOS/Froganize
├── MacOS/FroganizeFileOps
└── Library/LoginItems/FroganizeScreenshotAgent.app/
    └── Contents/MacOS/ScreenshotRenamer
```

The three execution roles remain the Qt main app, the deterministic Python
helper, and the single nested Swift binary shared by agent and control modes.
The builder freezes the helper separately, builds the Swift component, copies
both into fixed locations, updates version metadata to 0.3.0, signs helper →
nested component → outer app, verifies the deep signature, and runs a
non-launching bundle structure smoke test.

## Verification record

Implementation checkpoints completed:

- full Python suite: 286 passed, including Screenshot Intelligence, organizer,
  packaging, public-repository, and file-safety regressions;
- Swift self-test: 55 isolated checks passed, including invalid provider
  response, non-retryable AI failure, retryable network failure, and missing
  API-key handling;
- real Swift broker → Python configure/rename/undo E2E: 58 checks passed with
  the installed console helper;
- Python 0.3.0 sdist and wheel build: passed;
- Swift Release app build and strict signature verification: passed;
- real unified local bundle build: passed;
- unified structure smoke and strict deep signature verification: passed;
- frozen main-window launch against disposable HOME/Desktop/state paths: passed.

No live provider request, real API key, real Desktop mutation, Git commit, Git
push, paid action, Developer ID signing, or notarization was performed.

## Known limitations

1. The Swift agent and Python organizer use different mutation locks. They still
   fail safely through snapshot revalidation and atomic rename, but do not yet
   serialize every cross-feature mutation behind one shared lock.
2. Screenshot activity and archive history are projected separately; there is no
   complete unified activity Timeline yet.
3. Launch-at-login is intentionally deferred. A nested agent requires outer-app
   `SMAppService` ownership; using the nested app's `.mainApp` registration would
   be incorrect.
4. Provider tests use deterministic fixtures and fake helpers, not live paid
   requests.
5. The local bundle is arm64, ad-hoc signed, and not notarized.
6. The helper does not attempt AI analysis of ordinary files, PDFs, Office
   documents, folders, or videos.
7. The deterministic Swift self-test covers the provider parser, error
   classification, contract, process bridge, and real helper path. A future
   App-target test harness should still exercise FolderWatcher event coalescing,
   Keychain absence, and full AppModel status transitions without a live paid
   provider.

## Next recommended stage

The highest-value next step is a controlled user trial of the unified local
bundle with a disposable screenshot folder and a user-supplied provider key.
Capture usability and failure evidence before adding features. After that,
consolidate the Swift source into the main repository and add outer-app-owned
launch-at-login plus a unified activity presentation without merging the two
undo semantics.
