# Froganize Release Checklist

Use this checklist for every public preview or release. It is intentionally
strict because Froganize moves user files.

The current repository is preparing a source-only macOS public beta at
`https://github.com/liwengtai-sudo/Froganize`. It has no verified project
contact. Developer ID signing and
notarization are not blockers for a source-only release because no public app
binary is included or promised.

The public website domain is `www.froganize.com`, but its GitHub Pages site,
ownership verification, DNS records, and HTTPS status are not configured yet.
The source repository must work at its default GitHub URL before DNS changes
make the custom domain publicly reachable.

## 1. Release decision

- [x] Define the release audience: source-only macOS public beta.
- [ ] Choose the version according to Semantic Versioning.
- [ ] Confirm the version is identical in package metadata, runtime output,
      documentation, and the changelog.
- [ ] Document supported macOS and Python versions.
- [ ] Confirm that unsupported platforms and features are clearly labeled.
- [ ] Freeze unrelated feature work until verification is complete.

## 2. Repository and contact readiness

- [x] Configure and verify the canonical GitHub remote URL.
- [ ] **BLOCKER:** enable GitHub Issues and confirm all issue forms render.
- [ ] **BLOCKER:** enable GitHub Private Vulnerability Reporting and submit a
      private test report visible only to maintainers.
- [ ] **BLOCKER:** publish a monitored private conduct-reporting contact.
- [ ] Decide whether to publish a general support contact or use Issues only.
- [ ] Replace any temporary contact wording after the channels above exist.
- [x] Add the canonical repository URL to package metadata and public docs.
- [x] Add website canonical, social-preview, robots, sitemap, and GitHub Pages
      deployment metadata for `www.froganize.com`.
- [ ] Confirm Alibaba Cloud domain-holder verification.
- [ ] Verify `froganize.com` in GitHub Pages before adding serving records.
- [ ] Configure reviewed apex and `www` DNS records and enforce HTTPS.
- [ ] Configure repository description, topics, social preview, and license
      detection.
- [ ] Confirm branch protection and required CI checks on the default branch.

Do not invent an email address or publish an unmonitored contact.

## 3. Product and filesystem safety

- [ ] Opening the app performs assessment only and never moves files.
- [ ] Nothing moves when the app opens or refreshes its assessment.
- [ ] Pressing **Collect Desktop** consumes only the exact saved plan of every
      safely movable top-level item; execution cannot silently broaden it.
- [ ] Desktop, workspace, Timeline, source, and destination boundaries are
      resolved and revalidated.
- [ ] Root, home, Desktop-as-workspace, overlap, and path-traversal cases stop
      before mutation.
- [ ] Symbolic links are not followed and external targets cannot be reached.
- [ ] Whole folders remain intact and unsafe descendants block that folder.
- [ ] The assessment plan is the exact plan consumed during execution.
- [ ] File and folder changes after assessment are detected.
- [ ] Target occupancy is checked immediately before move.
- [ ] Case-insensitive and compound-extension conflicts never overwrite.
- [ ] History append failure rolls back the affected move safely.
- [ ] Undo never overwrites an occupied source and reports missing targets.
- [ ] Partial failures are reported without corrupting unrelated items.
- [ ] Disk-full, permissions, missing source, damaged config, damaged history,
      and concurrent-operation behavior have clear user-facing results.

## 4. Privacy and local web review

- [ ] Confirm no telemetry, analytics, remote assets, accounts, or unexpected
      network requests were introduced. The only expected Provider requests
      are an explicitly invoked connection test and, after upload consent is
      enabled, a matching screenshot sent for processing.
- [ ] Confirm opening or refreshing the Screenshot Intelligence panel, changing
      the folder/provider/model, and saving local settings do not contact a
      Provider.
- [ ] Confirm ordinary Desktop organization does not read, index, upload, log,
      or store file contents; confirm screenshot bytes and API keys are never
      written to Froganize activity/history.
- [ ] Review every history field and document local retention.
- [ ] Bind the dashboard only to `127.0.0.1`.
- [ ] Verify Host checks, POST action tokens, body limits, CSP, frame denial,
      referrer policy, no-store, and nosniff headers.
- [ ] Verify filenames and paths are rendered as text, not injected HTML.
- [ ] Check open/reveal endpoints cannot accept arbitrary paths.
- [ ] Review [PRIVACY.md](../PRIVACY.md) against actual behavior.
- [ ] Redact usernames, paths, filenames, workspace IDs, tokens, and personal
      data from screenshots, demos, logs, and fixtures.

## 5. Automated verification

Run from a clean virtual environment:

```bash
python3 -m venv .venv-release
source .venv-release/bin/activate
python -m pip install --upgrade pip build
python -m pip install -e ".[dev,gui]"
python scripts/check_public_repo.py
python -m pytest
python -m build
```

- [ ] All tests pass on macOS with Python 3.11.
- [ ] All tests pass on macOS with Python 3.12.
- [ ] All tests pass on macOS with Python 3.13.
- [ ] CI passes for the exact release commit.
- [ ] Tests use only pytest or explicitly created temporary directories.
- [ ] Tests never touch a real Desktop, home, Downloads, or Documents directory.
- [ ] The source distribution and wheel both build without warnings.
- [ ] Inspect archive contents for missing assets and accidental private files.
- [ ] Install the built wheel into a second clean environment.
- [ ] Verify `dropnest --version`, `dropnest --help`, imports, packaged SVG/UI
      assets, and native application startup from the installed wheel.

Remove `.venv-release` after verification; never commit it.

## 6. Manual synthetic-data acceptance

- [ ] Create a disposable sandbox outside all personal file trees.
- [ ] Include synthetic files, whole folders, hidden items, temporary items,
      symbolic links, Unicode names, compound suffixes, and conflicts.
- [ ] Verify safely movable and explicitly skipped/unsafe results.
- [ ] Verify preview/assessment makes no filesystem changes.
- [ ] Press **Collect Desktop** once and compare every planned destination with
      the resulting cross-month history batch.
- [ ] Verify a nested folder modification invalidates its saved plan.
- [ ] Verify a newly occupied destination is never overwritten.
- [ ] Undo the latest batch and confirm conflicts remain untouched.
- [ ] Inspect organization history and confirm it contains only expected
      operation metadata. Inspect Screenshot Intelligence activity and confirm
      it contains expected rename/semantic metadata, but no screenshot bytes or
      API keys.
- [ ] Remove the synthetic sandbox after recording non-sensitive results.

## 7. Documentation and community

- [ ] README installation and quick-start steps work in a clean environment.
- [ ] Screenshots match the release and contain useful alt text.
- [ ] Architecture and requirements match shipped behavior.
- [ ] Changelog includes user-visible, security, privacy, and compatibility
      changes.
- [ ] Contributing, support, conduct, privacy, and security policies are linked
      from the repository homepage.
- [ ] Issue and pull request templates request safety and privacy impact.
- [ ] FAQ and limitations do not promise unsupported behavior.
- [ ] License headers and third-party asset attributions are complete.

## 8. macOS packaging (not part of the source-only beta)

Local packaging experiments already completed:

- [x] Build a self-contained Apple-silicon `.app` that does not depend on the
      checkout, system Python, or `.venv`.
- [x] Package a local unsigned DMG and generate its SHA-256 checksum.
- [x] Verify the frozen bundle on disposable Desktop/workspace paths.
- [x] State clearly that the launcher and unsigned DMG are local/developer tooling.
- [x] Do not describe an ad-hoc signature as Developer ID signing.
- [x] Explain current signing, notarization, and publication limitations accurately.

If a future release distributes a public `.app`, `.dmg`, or `.pkg`:

- [x] Provide an opt-in build path for Developer ID signing, `notarytool`,
      stapling, Gatekeeper assessment, and final-artifact checksums.
- [ ] **BLOCKER:** use a controlled Apple Developer ID identity.
- [ ] **BLOCKER:** enable hardened runtime where appropriate.
- [ ] **BLOCKER:** notarize the exact artifact and staple the ticket.
- [ ] Verify signatures with `codesign` and Gatekeeper assessment with
      `spctl` on a clean Mac.
- [ ] Test first launch, upgrade, uninstall, and quarantine behavior.
- [ ] Document application data and launcher removal.
- [ ] Generate and publish SHA-256 checksums.
- [ ] Preserve signing and notarization credentials only in protected release
      infrastructure, never in the repository.

## 9. Git and publication

- [ ] Review `git status` and the complete diff.
- [ ] Confirm generated media and binaries are intentional and reasonably sized.
- [ ] Search tracked files for secrets and absolute personal paths.
- [ ] Run `python scripts/check_public_repo.py` and resolve findings in both the
      current tree and committed history; deleting text in a later commit is
      not sufficient.
- [ ] Confirm no `.dropnest`, real user files, histories, virtual environments,
      or local app bundles are tracked.
- [ ] Confirm the included Swift Screenshot Intelligence source builds and its
      self-test plus Keychain policy check pass from a clean clone.
- [ ] Create a reviewed release commit.
- [ ] Create a signed or otherwise policy-compliant annotated version tag.
- [ ] Build artifacts from that exact tag in trusted CI.
- [ ] Publish release notes and checksums.
- [ ] Do not configure CI to publish merely because a branch was pushed.
- [ ] Verify download, installation, launch, assessment, archive, and undo from
      the public artifact.

## 10. Post-release

- [ ] Monitor private security reports, Issues, and CI.
- [ ] Record known problems without exposing sensitive details.
- [ ] Prepare rollback or withdrawal instructions for a data-safety regression.
- [ ] Update the roadmap from verified feedback rather than download metrics
      alone.
- [ ] Add the release link to the changelog only after the canonical repository
      URL exists.
