# Froganize / DropNest task list

## Current project scope (2026-09-14)

Froganize is preparing for a **source-only open-source public beta**. Active work covers
filesystem safety, code quality, tests, a concise source setup, an accurate
README, and reproducible source installation. Signed/notarized binaries, App
Store distribution, and automated public releases are not current goals.

Past packaging, website, and publicity tasks remain below as project history.
Their unchecked release items are archived context, not the current roadmap,
and must not be resumed without an explicit product decision.

Every task must be independently testable. Safety and planning are completed
before the first real file move is introduced.

> Product-direction note: sections 1–22 record earlier development and release
> experiments. Sections 23–24 record the current one-click, monthly archive
> mainline and its read-only organization calendar.

## 1. Project foundation

- [x] Create the project directory and local Git repository.
- [x] Create `.venv`, `.gitignore`, `pyproject.toml`, source, docs, and tests.
- [x] Declare Python 3.11+ and current version 0.3.0.
- [x] Verify installation in the new isolated virtual environment.
- [x] Add the `dropnest` console entry point, `--help`, and `--version`.
- [x] Add package import and CLI smoke tests.

## 2. Product contract and architecture

- [x] Define the low-friction chronological archive product intent.
- [x] Document `st_mtime`, whole-folder handling, preview semantics, non-goals,
  and the local-first safety principles.
- [x] Define CLI as an adapter over reusable application services.
- [x] Define the required development order without creating empty modules.

## 3. Workspace initialization and safety validation

- [x] Define the minimal versioned `config.json` schema.
- [x] Resolve the explicit workspace and derive fixed managed paths.
- [x] Reject root, home, Desktop, containment violations, overlapping managed
  paths, managed-directory symlinks, traversal escapes, and unsafe permissions.
- [x] Implement idempotent creation of `Inbox`, `Timeline`, `.dropnest`,
  configuration, and history.
- [x] Preserve existing directories and configuration unless replacement is
  explicitly requested.
- [x] Validate all workspace-wide invariants before mutation.
- [x] Test only with `tmp_path`: valid init, repeated init, preserved content,
  preserved config, root/home/Desktop rejection, overlaps, traversal, symlink
  escape, and permission failures.

## 4. Deterministic move planning

- [x] Introduce only the models needed for workspace, item snapshots, plan
  entries, and plans.
- [x] Scan only direct `Inbox` children without following symbolic links.
- [x] Implement explicit reasons for hidden, temporary, symbolic-link,
  unreadable, and reliably detected cloud-placeholder skips.
- [x] Centralize the classification-time policy with MVP default `st_mtime`.
- [x] Map files and whole folders to `Timeline/YYYY/YYYY-MM`.
- [x] Capture metadata needed to detect changes before execution.
- [x] Generate deterministic, case-insensitively conflict-safe names, including
  no suffix, single suffix, compound suffix, folders, existing destinations,
  and collisions within one plan.
- [x] Test empty Inbox, files, whole folders, cross-year dates, local timezone
  conversion, all skip rules, deterministic ordering, and conflict variants.

## 5. Read-only preview

- [x] Implement a preview application service returning the shared `SortPlan`.
- [x] Add `dropnest preview PATH` as a thin renderer.
- [x] Display source, final target, time used, conflict rename, and skip reason.
- [x] Prove preview makes no filesystem or history changes.
- [x] Prove preview and sort call the same planner.
- [x] Document and test that preview is a snapshot and sort replans current
  state rather than executing stale output.

## 6. Checked execution

- [x] Decide and document whether a workspace process lock is required for MVP.
- [x] Implement an executor that consumes, but does not redesign, a `SortPlan`.
- [x] Revalidate the complete workspace before the first move.
- [x] Before each move, recheck source identity/metadata, containment,
  non-self destination, and exact target vacancy.
- [x] Use a move primitive that cannot silently replace an occupied target.
- [x] Create only required `Timeline/YYYY/YYYY-MM` directories.
- [x] Report source disappearance/change, target races, permissions, locks, and
  insufficient space as distinct item outcomes.
- [x] Continue safe independent items after item-level failure.
- [x] Test files, whole folders, no overwrite, changed/disappeared sources,
  target races, partial item failure, and workspace-wide preflight failure.

## 7. History

- [x] Define versioned JSONL move and undo record schemas.
- [x] Generate unique operation and batch IDs and UTC event timestamps.
- [x] Append complete records after successful moves; optionally record
  failures without making them undo-eligible.
- [x] Validate records strictly and report malformed/incomplete history.
- [x] Confirm history contains metadata only and never file content.
- [x] Test append behavior, multiple batches, partial batches, and corruption.

## 8. Undo

- [x] Select outstanding operations from the most recent successful sort batch.
- [x] Build restoration actions from validated history.
- [x] Restore exact original paths without overwriting conflicts.
- [x] Report missing targets and continue independent restorations.
- [x] Append undo outcomes and never restore a completed operation twice.
- [x] Allow retry of unresolved operations without silently proceeding to an
  older batch.
- [x] Test full, partial, repeated, conflict-retry, missing-target, and corrupt
  history cases.

## 9. Read-only status

- [x] Return a structured status report for workspace validity, sortable,
  skipped and unreadable counts, archive month count, configuration/history
  health, and latest successful batch summary.
- [x] Add `dropnest status PATH` as a thin renderer.
- [x] Prove status creates or changes nothing.

## 10. CLI completion and error experience

- [x] Add thin `init`, `sort`, and `undo` adapters around completed services.
- [x] Keep all organizing, safety, and history decisions out of `cli.py`.
- [x] Define stable exit codes and concise user-facing errors.
- [x] Add explicit debug traceback behavior.
- [x] Print readable per-item output and batch summaries.
- [x] Add command-level integration tests.

## 11. MVP verification and documentation

- [x] Run initialization, safety, planning, preview, execution, conflict,
  history, undo, status, and CLI tests with `pytest`.
- [x] Confirm every fixture is inside the project or pytest `tmp_path`.
- [x] Verify install and commands in a fresh Python 3.11+ virtual environment.
- [x] Update README examples to match implemented behavior.
- [x] Record cloud-placeholder, concurrency, filesystem, and platform limits.
- [x] Inspect the final Git diff and generated-file exclusions.

## 12. Controlled dogfooding

- [x] Add a real console-script acceptance scenario under pytest `tmp_path`.
- [x] Exercise cross-year/month files and a complete nested folder.
- [x] Exercise hidden, temporary, placeholder, and symlink handling without
  letting DropNest follow external content.
- [x] Verify compound-suffix conflict naming and preservation of an existing
  target.
- [x] Prove preview tree equality before and after the command.
- [x] Verify sort, status, metadata-only history, undo, and repeated undo.
- [x] Run the acceptance scenario and complete suite in both development and
  clean verification environments.
- [x] Record results and the gate for automatic monitoring.

## 13. Post-MVP preparation

- [x] Review the license, package metadata, changelog, and release checklist.
- [x] Add community health files, issue forms, a pull request template, and CI.
- [x] Create a coherent Froganize brand kit, screenshots, demo media, and
  social publishing kit.
- [x] Keep automatic watching, native menu-bar UI, content classification, and
  publishing out of the local dashboard implementation.
- [ ] Do not commit, push, create a repository, or publish without explicit
  authorization.

## 14. Local Desktop dashboard

- [x] Add `dropnest web WORKSPACE` without adding runtime dependencies.
- [x] Bind only to `127.0.0.1` and fix validated Desktop/Timeline paths per
  server.
- [x] Require a random same-origin action token for every POST operation.
- [x] Expose status, assessment, selected archive, Desktop undo, and fixed
  Desktop/Timeline Finder actions.
- [x] Reuse existing conflict, history, lock, and workspace services.
- [x] Add responsive HTML/CSS/JS with no external assets or file uploads.
- [x] Require a saved assessment and explicit confirmation before mutation.
- [x] Test invalid Host, missing token, read-only assessment, selected
  archive/undo, fixed open/reveal targets, and invalid ports over loopback.
- [x] Package web assets in the wheel and verify in a clean environment.
- [x] Install and launch a no-terminal macOS app wrapper for this machine.
- [x] Complete read-only browser and visual layout inspection.

## 15. Desktop-first workflow

- [x] Make Desktop the primary web source without requiring Inbox.
- [x] Scan and display only Desktop direct children.
- [x] Reduce the primary UI to keep-on-Desktop, suggested-archive, and
  leave-untouched outcomes.
- [x] Suggest archive after more than 7 completed days without modification.
- [x] Start every assessment with no selected items.
- [x] Keep files and folders selectable only as complete top-level items.
- [x] Compute a folder's time from its newest descendant metadata.
- [x] Fingerprint folder trees without reading content or following links.
- [x] Reject deep changes between assessment and movement.
- [x] Consume each assessment at most once.
- [x] Execute only exact selected safe names from the saved plan.
- [x] Restore the latest Desktop batch to exact original top-level paths.
- [x] Exclude the DropNest Desktop launcher from assessment.
- [x] Create a custom app icon and safe Desktop shortcut installer.
- [x] Verify wide and 390px layouts without horizontal overflow.
- [x] Verify the real UI flow: archive two temporary projects and undo both.
- [x] Keep legacy Inbox behavior covered by regression tests.

## 16. Public release gate (archived; not current scope)

- [x] Remove personal absolute paths from tracked source and documentation.
- [x] Provide portable source-checkout installation and launcher instructions.
- [x] Build and inspect wheel and source distributions.
- [x] Add an English landing README and a Simplified Chinese README.
- [x] Add an image-led one-minute tutorial and synthetic Before/After demo.
- [ ] Add the canonical GitHub repository URL after the remote exists.
- [ ] Add the maintainer's chosen public contact and Xiaohongshu profile.
- [ ] Enable GitHub private vulnerability reporting.
- [ ] Sign and notarize a distributable macOS application.
- [ ] Add Star History only after the public repository has real history.

## 17. Conservative cleanup recommendations

- [x] Add a collapsed, default-unchecked cleanup utility for high-confidence
  regular files.
- [x] Keep folders, arbitrary hidden files, links, and cloud placeholders out.
- [x] Reuse the one-use assessment capability as an action-specific allowlist.
- [x] Recheck direct-child scope, type, symlink state, rule, and snapshot.
- [x] Move only confirmed items to recoverable macOS Trash through Finder.
- [x] Never expose permanent deletion, `rm`, or empty-Trash controls.
- [x] Isolate per-item failures and keep all tests in temporary directories.

## 18. Self-contained macOS distribution candidate (archived experiment)

- [x] Add an application entry point independent of the checkout and `.venv`.
- [x] Replace the browser/loopback host with a real PySide6 application window.
- [x] Call a framework-free Desktop application service instead of an HTTP API.
- [x] Bundle Python, Qt, DropNest modules, GUI assets, and the Froganize icon.
- [x] Build an Apple-silicon `.app`, unsigned test DMG, and SHA-256 checksum.
- [x] Smoke-test the frozen GUI only with disposable Desktop/workspace paths and
  assert that no legacy `server.json` state is created.
- [x] Keep only one local Desktop app, preserve the old launcher as a project
  backup, and verify repeated opening reuses one native process.
- [ ] Join the Apple Developer Program and create a protected Developer ID setup.
- [x] Add an opt-in Developer ID, notarytool, stapling, Gatekeeper, and checksum
  release pipeline that never stores credentials in the repository.
- [ ] Add hardened runtime, notarize, staple, and verify on a clean second Mac.
- [ ] Publish through GitHub Releases before investing in a custom download site.

## 19. Local official website prototype (archived experiment)

- [x] Inherit the current local dashboard's cream, cobalt, yellow, coral,
  system-type, rounded-card, and restrained-shadow design system.
- [x] Keep the static site independent from organizer APIs and filesystem
  actions.
- [x] Reuse the approved mascot, welcome scene, organizing scene, and synthetic
  product screenshot.
- [x] Add a coherent four-scene mascot story: clutter, folder-shaped magic
  wand, learning, and calm mastery.
- [x] Explain that story magic maps to assessment, explicit selection,
  confirmation, and undo rather than automatic movement.
- [x] Use no remote font, analytics, account, cookie, telemetry, or network
  asset.
- [x] Support direct `index.html` opening plus optional loopback HTTP preview.
- [x] Verify 1440px and 390px layouts, lazy image loading, and zero horizontal
  overflow in a real browser.
- [x] Add static structure, asset, accessibility, and responsive-style tests.
- [ ] Open the public download route only after signing, notarization,
  clean-Mac verification, and a real public release URL exist.

## 20. Official website V2 product-first upgrade (archived experiment)

- [x] Move product definition and the Before → decision → After proof ahead of
  the mascot story.
- [x] Standardize the public workflow as Inspect → Suggest → Confirm → Undo.
- [x] Promote a privacy-safe real dashboard capture with a readable mobile
  variant.
- [x] Present Local First accurately: ordinary organization is metadata-only
  and local; Screenshot Intelligence is a separate explicit opt-in upload
  boundary; moves remain confirmed, no-overwrite, and reversible.
- [x] Preserve all four mascot story scenes; their V3 presentation is tracked
  below.
- [x] Add a JavaScript-free mobile navigation and 44px touch targets.
- [x] Improve text contrast, focus visibility, Safari blur fallback, responsive
  layouts, and image loading behavior.
- [x] Add honest, local development-progress and privacy pages instead of fake
  GitHub or download links.
- [x] Add Open Graph, Twitter, Apple touch icon, JSON-LD, robots, and social
  preview foundations without inventing a public domain.
- [ ] Add canonical, `og:url`, absolute `og:image`, and `sitemap.xml` only after
  the public domain is confirmed.

## 21. Official website V3 simplification and continuous story (archived experiment)

- [x] Simplify the visual hierarchy by reducing decorative cards, repeated
  labels, competing calls to action, and unnecessary section framing.
- [x] Replace the former hero slogan with
  “给桌面一点整理魔法。” while keeping a direct product explanation nearby.
- [x] Standardize the mascot's Chinese nickname as “蛙仔” across the website
  and its supporting documentation.
- [x] Provide download entry points in both the header and hero; until a real
  public artifact exists, route both to the honest release-status section.
- [x] Present the four mascot scenes as a continuous illustrated narrative that
  users encounter naturally, without a separate “listen to the story” CTA.
- [x] Blend story artwork into the page background with gradients, open space,
  and frameless composition instead of independent photo cards.
- [ ] Replace the release-status anchors with one stable public download URL
  only after signing, notarization, clean-Mac verification, and publication.

## 22. Froganize 0.3 unified prototype

- [x] Audit the Python organizer and the original Swift screenshot prototype
  without resetting the existing dirty worktree.
- [x] Add a strict schema-v1 JSON stdin/stdout contract and `froganize-fileops`
  helper entry point.
- [x] Make Python the deterministic authority for screenshot-folder
  authorization, rename, activity, crash recovery, and rename undo.
- [x] Remove the Swift direct-file-mutation fallback and require the helper.
- [x] Capture screenshot identity before AI and revalidate it after AI returns.
- [x] Make screenshot upload explicit opt-in and packaged API keys Keychain-only.
- [x] Replace the read-only Screenshot Intelligence launcher with a complete
  main-window panel for folder, consent, enablement, provider/model, Keychain
  credentials, connection testing, process-latest, activity, and rename undo.
- [x] Pass newly entered API keys only through child-process stdin to the fixed
  Swift `--control` entry; exclude them from argv, environment variables, logs,
  history, configuration files, and the file-operation protocol.
- [x] Keep provider traffic action-bound: only an explicit connection test or
  explicitly enabled screenshot processing may issue a real provider request.
- [x] Scope Inbox/Desktop archive history queries by active source.
- [x] Add a unified macOS builder for main app + helper + nested menu agent.
- [x] Validate component identity, version, containment, executability, and
  inside-out code-signing order, including the fixed nested control entry,
  without launching a real watcher.
- [x] Add deterministic Python, Swift, GUI, safety, and packaging regression
  tests using only temporary files and fake providers/helpers.
- [x] Move the sibling Swift source into the main Git repository with a
  parity-preserving build path and self-test.
- [ ] Add outer-app-owned launch-at-login registration.
- [ ] Add a unified activity presentation without merging archive and rename
  undo semantics.

## 23. One-click Desktop collection mainline

- [x] Add temporary-directory contract tests proving that one click creates no
  root-level batch folder and routes each item to `Timeline/YYYY/YYYY-MM/`.
- [x] Plan only Desktop direct children and include every safely movable regular
  file and whole folder without age groups or per-item selection.
- [x] Exclude Froganize/current and known old launchers, hidden items, temporary
  files, incomplete downloads, symlinks, reliable placeholders, unreadable
  entries, unsupported types, and anything else unsafe; report every reason.
- [x] Keep planning read-only and execute the exact same immutable plan after
  revalidating source snapshots and target vacancy.
- [x] Classify regular files by `st_mtime` and whole folders by the newest
  `mtime` in their readable tree; move folders intact and never overwrite.
- [x] Append all successful operations from one click under one history batch
  ID and safely undo that logical batch even when it spans multiple months.
- [x] Replace the native primary workflow with one `收好桌面` button;
  opening remains read-only and the click itself is explicit authorization, so
  no checkbox or second confirmation is added.
- [x] Show concise moved/skipped/failed results plus Open collection and Undo.
- [x] Use the frog and folder-magic-wand artwork for operation states without
  adding story screens; keep Screenshot Intelligence secondary.
- [x] Preserve and regression-test legacy `dropnest` Inbox sorting to
  `Timeline/YYYY/YYYY-MM/`.
- [x] Run focused safety tests, full `pytest`, frozen-app smoke tests, and a
  disposable Desktop end-to-end collect/undo test before replacing the local app.

## 24. Organization history calendar

- [x] Project validated JSONL organization history into a read-only calendar
  model without scanning or changing archived files.
- [x] Show history by local operation date with a frog-style native PySide6
  calendar, batch details, original names, destinations, and restore state.
- [x] Keep older batches read-only and expose undo only for the latest
  outstanding Desktop organization batch.
- [x] Recheck the selected batch ID while holding the workspace lock so a stale
  calendar cannot accidentally undo a newer batch.
- [x] Preserve no-overwrite undo behavior and surface occupied originals,
  missing destinations, and damaged history as explicit results.
- [x] Cover calendar projection, native UI, confirmation, successful undo,
  corrupted history, and stale-view races with temporary-directory tests.
- [x] Replace the repeated downscaled raster mascot with Retina-rendered SVG
  poses for idle, organizing, calendar selection, and successful completion.

## 25. Source-only GitHub public beta preparation

- [x] Audit tracked and untracked public candidates for credentials, personal
  paths, local histories, build output, and oversized files.
- [x] Detect sensitive content retained in Git history; the initial baseline
  contains a maintainer absolute path and must not be uploaded as-is.
- [x] Add a repeatable public-repository preflight and run it in CI.
- [x] Capture the current native dashboard with synthetic temporary data.
- [x] Align the GitHub Social Preview with the one-click product promise and
  validate all current repository media dimensions.
- [x] Align README, privacy, security, support, contribution, and tutorial
  documents with the one-click Desktop collection mainline.
- [x] Add third-party dependency notices and package the public documentation.
- [x] Migrate the complete Swift Screenshot Intelligence source, build scripts,
  privacy metadata, and self-test into this repository.
- [x] Build the unified local app from repository-owned sources and verify its
  nested component layout and strict deep signature.
- [ ] Perform the final diff review and create a local release-preparation
  commit only after explicit authorization.
- [ ] Replace or rewrite the one-commit local history so the public repository
  starts without the historical maintainer path; requires explicit authorization.
- [ ] Configure the GitHub remote, repository settings, and public links only
  after explicit upload authorization.
- [ ] Repeat install, tests, and screenshots from a fresh clone after the first
  public repository exists.
