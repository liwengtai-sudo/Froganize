# Privacy

Froganize is designed as a local-first macOS desktop organizer. The current
source-only beta candidate has no accounts, advertising, analytics, telemetry, or cloud
sync. Normal Desktop assessment and organization make no remote request.

## What the app inspects

During a Desktop assessment, Froganize inspects filesystem metadata needed to
make and verify a plan:

- top-level names and item types;
- paths relative to the authorized source and archive;
- modification times;
- size, mode, device, and inode metadata used in snapshots;
- directory entries and metadata for descendants of a top-level folder.

It does not read or index file contents. Every safe top-level folder is
evaluated and moved as one whole item; nested items are never split into
separate operations. Symbolic links are not followed.

## Screenshot Intelligence (optional)

Screenshot Intelligence is off by default. Its controls are visible inside the
main Froganize window, and its Swift component is contained under
`swift/ScreenshotIntelligence/`. Merely opening the panel, refreshing its
status, choosing a folder/provider/model, or saving local settings does not
contact a provider. A real provider request occurs only when the user either:

- explicitly clicks the connection-test action; or
- accepts the upload disclosure and enables screenshot processing.

When processing is enabled, the nested Swift screenshot component:

- watches only the folder explicitly selected by the user;
- considers only filenames that match supported macOS system screenshot
  patterns and supported image extensions;
- skips symbolic links before any upload;
- sends the matched screenshot image to the AI Provider selected in settings;
- receives a proposed title, summary, category, confidence, and sensitivity
  flag; and
- asks a local deterministic helper to validate and perform the rename.

Other Desktop files are not uploaded by Screenshot Intelligence. Ordinary PDF,
Office, folder, video, and document contents are not sent for AI analysis. The
provider processes uploaded screenshots under that provider's own terms and
privacy policy; users should not enable the feature for screenshots they are not
comfortable sending to that provider.

Provider API keys are stored in macOS Keychain by the packaged application. A
key entered in the main panel necessarily exists briefly in local process
memory; Froganize passes it directly through a child process's stdin to the
fixed nested Swift executable, which writes it to Keychain. The key is not put
in command-line arguments, environment variables, stdout/stderr, application
logs, activity history, the Python file-operation JSON contract, configuration
files, or the repository. The Swift control response never echoes the key.
Source-development overrides are intentionally separate from this packaged
credential path.

Filename and path metadata can itself be sensitive. Treat screenshots, logs,
issue reports, and history exports accordingly.

## What is stored

The selected workspace contains local metadata under `.dropnest`:

- `config.json` stores workspace configuration and a random workspace ID;
- `history.jsonl` stores append-only operation metadata, including original and
  destination paths, timestamps, item type, operation IDs, batch IDs, and
  outcomes;
- `workspace.lock` may temporarily record process coordination metadata while a
  mutating operation runs.

History does not contain file contents, but paths may reveal filenames and
folder names. It remains on the user's machine until the user removes it.
Deleting or editing history can make undo and status reporting unavailable or
invalid; back it up first if recovery matters.

Screenshot Intelligence stores non-secret state under
`~/Library/Application Support/Froganize/` by default:

- the authorized screenshot folder and configuration metadata;
- append-only rename/undo activity, including filenames, semantic title,
  summary, category, provider/model identifiers, timestamps, and file snapshot
  metadata;
- a short-lived operation journal and lock used for safe mutation recovery.

Screenshot image bytes and API keys are not written to this activity history.
Filenames, summaries, and paths can still be sensitive.

## Local dashboard

The dashboard is served from the user's machine and binds to `127.0.0.1`.
Packaged scripts, styles, fonts, and images are served locally. The current
application does not load analytics or third-party page assets.

The local server uses a random action token for state-changing requests and
restricts accepted Host headers. Other software running under the user's
account may still be able to observe local processes or files according to
macOS permissions; Froganize is not a sandbox or encryption product.

## Filesystem changes

Opening or refreshing the native dashboard only assesses metadata. Files move
only after the user presses **Collect Desktop**, which authorizes execution of
the exact saved plan of safely movable top-level items. Archive moves go to the
configured local `Timeline/YYYY/YYYY-MM/` hierarchy. Existing items are not
overwritten, and the latest successful archive batch can be undone subject to
conflicts and history availability.

A separate, default-unchecked cleanup group may move explicitly confirmed,
high-confidence temporary residue to macOS Trash through Finder. Froganize does
not permanently delete files or empty Trash. Cleanup recovery is handled through
Finder Trash. Background monitoring and screenshot upload are limited to the
optional, explicitly enabled Screenshot Intelligence behavior described above.
The only other provider request is the user's explicit connection test. Neither
path changes the local-only, metadata-only boundary for ordinary organization.

## macOS and browser data

macOS, Finder, the selected browser, Python, and any package-installation tools
may maintain their own logs, recent-item lists, caches, or network behavior.
Those products are governed by their providers and system settings, not this
policy.

If a user downloads dependencies, clones the repository, opens a GitHub issue,
or participates in a future hosted community, the relevant hosting service may
process data independently. Do not post personal files, unredacted absolute
paths, or `.dropnest/history.jsonl` publicly.

## Data control

Application-managed organization data is in the user-selected local workspace;
Screenshot Intelligence state is in the local Application Support directory.
To stop automatic screenshot processing, turn it off in the main Screenshot
Intelligence panel (or quit the nested component). To remove local metadata,
first decide whether archive and screenshot-rename undo history is still
needed, then remove the corresponding `.dropnest` and Application Support data
manually. Provider credentials can be removed through the same panel or from
macOS Keychain.

The current source-only beta has no remote account or server-side profile to delete.

## Changes to this policy

New telemetry, accounts, broader content inspection, or cloud features would
require an explicit product decision, documentation update, and clear user
consent before release. Material privacy changes will be recorded in
[CHANGELOG.md](CHANGELOG.md).
