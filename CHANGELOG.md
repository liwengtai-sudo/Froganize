# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project intends to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) when public releases
begin.

## [Unreleased]

### Added

- A source-only public-repository preflight that rejects common credential,
  personal-path, local-history, build-output, and oversized-file mistakes.
- A reproducible, synthetic screenshot of the current native one-click
  dashboard and third-party dependency notices.

### Changed

- Reframed the next milestone as a source-only GitHub public beta; no signed or
  notarized binary is claimed.
- Aligned public documentation with the current one-click monthly collection
  flow instead of the retired seven-day selection workflow.
- Migrated the complete optional Swift Screenshot Intelligence source, build
  scripts, privacy descriptions, and self-test into this repository.

- Replaced the Screenshot Intelligence status/launcher page with a complete
  control panel inside the main Froganize window.
- Reused the fixed nested Swift executable in `--control` mode for screenshot
  settings, Keychain credential actions, connection testing, process-latest,
  status, activity, and rename undo; no fourth executable was added.
- Restricted API-key transfer to local process memory and child-process stdin.
  Keys are excluded from argv, environment variables, logs, histories,
  configuration files, and the Python file-operation protocol.
- Kept real provider requests behind either a user-initiated connection test or
  explicitly enabled screenshot processing. Ordinary organization remains
  metadata-only and local.

## [0.3.0] - 2026-08-12

> Unified local prototype. This version has not yet been represented by a
> public Git tag or notarized macOS release.

### Added

- Opt-in Screenshot Intelligence with a Swift menu-bar agent and existing
  Vision-provider support.
- A strict versioned JSON stdin/stdout contract and deterministic Python helper
  for screenshot-folder authorization, collision-safe rename, activity, crash
  recovery, and typed rename undo.
- A read-only Screenshot Intelligence status page in the native main window.
- A unified local bundle containing the main app, file-operations helper, and
  nested menu-bar agent.
- Open-source contribution, conduct, security, privacy, and support policies.
- Structured issue forms, pull request guidance, Dependabot configuration, and
  a macOS test-and-build CI workflow.
- A release checklist for contact channels, privacy review, file-safety review,
  packaging, signing, and public communication.
- English and Simplified Chinese landing documentation plus an image-led
  one-minute tutorial.
- A deterministic synthetic Before → After → Undo demo generator.
- A complete Froganize media kit: repository banners, product screenshots,
  GIF walkthrough, social preview, brand scenes, and Xiaohongshu assets.
- A portable source-checkout macOS launcher that stores its selected workspace
  inside the installed app bundle instead of embedding a maintainer path.
- A branded browser favicon and deterministic media validation tooling.
- Conservative, default-unchecked cleanup recommendations for obvious temporary
  residue, with separate confirmation and recoverable macOS Trash execution.

### Changed

- Unified user-visible screenshot naming under the Froganize product identity.
- Made screenshot upload explicit opt-in and packaged provider credentials
  Keychain-only.
- Removed direct Swift rename/undo fallback; Python is now the deterministic
  mutation authority.
- Scoped archive history selection by active Desktop or compatibility Inbox so
  one workflow cannot undo the other's latest batch.
- Standardized the public product name as Froganize while retaining `dropnest`
  as the Python package, CLI, metadata, and compatibility interface.
- Modernized package metadata and source-distribution contents for a future
  source-only public preview.
- Simplified the Desktop mainline to three visible outcomes: keep on Desktop,
  suggested archive, and leave untouched.
- Changed the archive suggestion threshold from more than 30 days to more than
  7 completed days, with every assessment starting unchecked.
- Moved conservative cleanup recommendations into a collapsed More tools
  utility while keeping permanent deletion and empty-Trash operations out of
  scope.

### Security

- Added strict JSON field, Unicode, size, UUID, snapshot, and AI-category
  validation plus request idempotency.
- Added authorized-root/direct-child enforcement, post-AI source revalidation,
  case-insensitive no-overwrite naming, write-ahead recovery, and history-write
  rollback for screenshot rename and undo.
- Kept ordinary file organization metadata-only and local; only explicitly
  enabled matching screenshots may be uploaded to the selected provider.

## [0.2.0] - 2026-07-29

> Local developer preview. This version has not yet been represented by a
> public Git tag or production macOS release.

### Added

- Local-only Desktop assessment dashboard with four age/safety groups.
- Explicit item selection and confirmation before archive.
- Whole-folder metadata assessment using the newest descendant modification
  time.
- Deterministic saved plans and change detection between assessment and move.
- Archive of selected items into `Timeline/YYYY/YYYY-MM/`.
- Latest-batch Desktop undo backed by append-only JSONL history.
- Finder open/reveal actions restricted to fixed, assessed locations.
- Froganize visual identity, mascot, and macOS developer launcher.

### Security

- Loopback-only HTTP binding, Host validation, random POST action token,
  restrictive response headers, and request-size limits.
- Workspace, Desktop, Timeline, source, and destination boundary validation.
- No-follow symbolic-link behavior, case-insensitive conflict allocation, and
  no-overwrite execution checks.

### Compatibility

- Retained and tested the original Inbox-based `init`, `preview`, `sort`,
  `status`, and `undo` CLI workflow.

## [0.1.0] - 2026-07-19

> Initial local MVP baseline; not a public production release.

### Added

- Python package and `dropnest` command-line entry point.
- Safe workspace initialization.
- Read-only monthly move planning for Inbox top-level items.
- Conflict-safe move execution, JSONL history, status, and latest-batch undo.
- Initial filesystem-safety and CLI regression tests.
