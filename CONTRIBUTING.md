# Contributing to Froganize

Thank you for helping improve Froganize, the macOS desktop organizer developed
in this repository under the Python package name `dropnest`.

Froganize is currently a **source-only macOS public beta**. Contributions are
welcome, especially when they improve filesystem safety, clarity, accessibility,
testing, documentation, or the quality of the local-first experience.

## Start with the project constraints

Before proposing a change, please read:

- [README.md](README.md) for the current product experience;
- [docs/requirements.md](docs/requirements.md) for expected behavior;
- [docs/architecture.md](docs/architecture.md) for trust boundaries and data
  flow;
- [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md) for reporting and
  data-handling expectations.

The following properties are foundational:

- opening the app is read-only;
- nothing moves until the user presses **Collect Desktop**;
- one collection consumes the exact saved plan of every safely movable direct
  Desktop child; execution cannot silently broaden that plan;
- folders move intact and are never silently split;
- symbolic links are not followed;
- existing files are never overwritten;
- preview/assessment and execution use the same saved plan;
- history stores metadata, never file contents;
- the local dashboard binds only to `127.0.0.1`;
- tests never touch a real Desktop, home directory, Downloads, or Documents.

Changes that weaken these properties require explicit design discussion and
new regression tests.

## Ways to contribute

- Reproduce and report a bug with redacted paths and synthetic files.
- Improve macOS accessibility, wording, or interaction design.
- Add tests for filesystem races, unusual names, permissions, or conflicts.
- Clarify documentation and first-run guidance.
- Propose a focused feature that preserves user control.
- Review changes for data-loss, privacy, and path-boundary risks.

Please use a GitHub Discussion, if enabled, or a feature request before starting
a large behavioral or architectural change. Do not use a public issue for a
security vulnerability; follow [SECURITY.md](SECURITY.md).

## Development setup

Requirements:

- macOS;
- Python 3.11 or newer;
- Git.

Create an isolated environment from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,gui]"
```

Confirm the installation:

```bash
dropnest --version
dropnest --help
python scripts/check_public_repo.py
python -m pytest
```

Build the distributable archives:

```bash
python -m pip install build
python -m build
```

## Safe manual testing

Automated tests use pytest temporary directories. Manual development must also
use synthetic data in a disposable directory.

```bash
SANDBOX="$(mktemp -d)"
mkdir -p "$SANDBOX/Desktop" "$SANDBOX/Workspace"
dropnest init "$SANDBOX/Workspace"
touch "$SANDBOX/Desktop/example.txt"
dropnest web "$SANDBOX/Workspace" \
  --desktop "$SANDBOX/Desktop" \
  --no-browser
```

Open the loopback URL printed by the command. Remove the sandbox only after
stopping the local server and confirming that it contains no personal data.

Never test a contribution by scanning or moving another person's real files.
Never add personal filenames, absolute home paths, history files, or screenshots
containing private information to a commit or issue.

## Making a change

1. Create a focused branch from an up-to-date default branch.
2. Add or update tests before changing filesystem behavior.
3. Keep CLI, web, and domain logic separated as described in the architecture.
4. Use user-readable errors for expected failures; do not swallow exceptions.
5. Update requirements, architecture, privacy, or security documentation when
   behavior changes.
6. Run the complete checks locally.
7. Review the diff for personal data and unrelated files.

Suggested branch names:

```text
fix/conflict-recheck
feat/assessment-filter
docs/first-run-guide
test/symlink-race
```

## Testing expectations

Run:

```bash
python scripts/check_public_repo.py
python -m pytest
python -m build
```

A filesystem change should normally cover:

- the successful path;
- missing and unreadable sources;
- symbolic links and path escapes;
- case-insensitive name conflicts;
- source changes between assessment and execution;
- no-overwrite behavior;
- history append or undo failure;
- empty and unusual Unicode names where the filesystem permits them.

Use `tmp_path` or another test-owned temporary directory. Monkeypatch the home
or Desktop path when needed. A test that depends on a contributor's machine
layout is not acceptable.

## Code and documentation style

- Prefer small functions with explicit inputs and return values.
- Keep planning read-only and execution mutation-only.
- Use `pathlib.Path` consistently for filesystem paths.
- Treat filenames, timestamps, permissions, and history as untrusted input.
- Preserve deterministic ordering in plans and user-visible output.
- Keep dependencies minimal and justify any new runtime dependency.
- Write concise English for source documentation and preserve useful Chinese
  user documentation where applicable.
- Add alt text for meaningful images and avoid text that exists only inside an
  image.

There is no required formatter or linter yet. Match the existing style and keep
the full test suite passing.

## Pull requests

Keep each pull request focused enough to review safely. In the description,
explain:

- the user problem;
- the chosen behavior;
- filesystem, privacy, and security impact;
- tests performed;
- screenshots for visible UI changes;
- documentation updated.

Complete the repository pull request checklist. Draft pull requests are welcome
for early design feedback, but they should not be presented as ready until all
required checks pass.

Maintainers may ask for changes when a patch is correct in normal conditions
but unsafe under races, permissions failures, case-insensitive filesystems, or
unexpected history data.

## Commit guidance

Use clear, imperative commit subjects. Conventional Commit prefixes are
welcome but not required:

```text
fix: recheck destination before moving
docs: explain local history retention
test: cover nested symlink metadata
```

Do not commit:

- `.venv`, caches, build output, or local app bundles;
- real `.dropnest` configuration or history;
- user files or absolute personal paths;
- secrets, tokens, signing identities, or notarization credentials.

## Community standards

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
General support guidance is in [SUPPORT.md](SUPPORT.md). By contributing, you
agree that your contribution may be distributed under the repository's
[MIT License](LICENSE).
