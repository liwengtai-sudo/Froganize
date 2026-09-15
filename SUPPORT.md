# Support

Froganize is currently a source-only macOS public beta. Community support is
best-effort and is intended to help reproduce project bugs, understand the
documented workflow, and evaluate focused feature ideas.

## Before asking for help

1. Read [README.md](README.md) and the current limitations.
2. Check existing GitHub issues after the public repository is available.
3. Confirm that you are using macOS and Python 3.11 or newer.
4. From an activated project virtual environment, run:

   ```bash
   dropnest --version
   python -m pytest
   ```

5. Reproduce the problem with synthetic files in a temporary directory whenever
   possible.

## Where to ask

- **Reproducible bug:** use the bug report issue form.
- **Non-sensitive file-safety problem:** use the safety report issue form.
- **Feature or workflow idea:** use the feature request issue form.
- **Security vulnerability:** report privately as described in
  [SECURITY.md](SECURITY.md).
- **Conduct concern:** follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

This local repository does not yet have a configured GitHub remote or verified
support address. Those channels must be added and tested before public release.

## Helpful diagnostic information

Include:

- Froganize/DropNest version or commit;
- macOS version and CPU architecture;
- Python version;
- command or UI action performed;
- expected result and actual result;
- concise terminal output without a traceback unless requested;
- minimal reproduction with temporary, synthetic files;
- whether the operation was assessment, archive, or undo.

Replace personal paths with placeholders such as `/Users/example/...`. Do not
upload real files, `.dropnest/history.jsonl`, tokens, workspace IDs, or
screenshots with private filenames.

## Current support boundaries

The following are not currently supported:

- Windows or Linux desktop releases;
- a signed or notarized universal macOS installer;
- automatic Desktop organization without opening the app and pressing
  **Collect Desktop**;
- recursive partial selection inside folders;
- cloud sync, accounts, network access, or multi-device state;
- content preview, content classification, deletion, or duplicate cleanup;
- archive recovery beyond the latest eligible outstanding successful batch;
- automatic launch-at-login registration for Screenshot Intelligence.

The compatibility Inbox CLI remains tested, but the primary product experience
is the local Desktop assessment dashboard.

## No recovery guarantee

Froganize is built to avoid overwrite and keep append-only operation history,
but the source-only beta is provided without a data-recovery guarantee. Keep
normal backups, review the assessment before pressing **Collect Desktop**, and
test with disposable data first.
