# Security Policy

Froganize moves files only after an explicit user action. A bug that crosses a path boundary,
overwrites data, follows an unsafe link, or permits an unauthorized local action
is treated as a security issue, even when it affects only the local machine.

## Supported versions

Froganize is currently a **source-only macOS public beta**, not a hardened,
signed, or notarized binary release.

| Version | Security support |
| --- | --- |
| `0.3.x` | Best-effort fixes on the active development line |
| `< 0.3` | Not supported |

Only the latest code on the default branch and the latest published preview,
when one exists, are eligible for fixes. There is currently no long-term
support branch or security service-level agreement.

## Report privately

Do not open a public issue with exploit details, personal paths, history
records, tokens, or proof-of-concept files.

When this repository is hosted on GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability** to create a private security advisory.
3. Include only the minimum synthetic information needed to reproduce the
   problem.

This route is available only if GitHub Private Vulnerability Reporting has been
enabled. If the button is unavailable, open a minimal public issue that says
only that you need a private security contact. Do **not** include vulnerability
details. A verified private contact must be configured before the first public
release.

For ordinary, non-sensitive safety bugs, use the repository's safety issue
template.

## What to include

- affected version or commit;
- macOS and Python versions;
- expected and observed behavior;
- whether files were moved, renamed, exposed, or made unavailable;
- a minimal reproduction using temporary directories and synthetic files;
- the relevant trust boundary, if known;
- any suggested mitigation.

Redact usernames, home paths, filenames, workspace IDs, history event IDs, and
screenshots. Never send real user files or file contents.

## Security scope

Examples of in-scope issues include:

- escaping Desktop, workspace, or Timeline boundaries;
- `..`, symlink, hard-link, mount, or race-condition abuse that causes an
  unauthorized move;
- overwriting or replacing an existing file or directory;
- moving an item that changed after assessment without detecting the change;
- unsafe history records causing restoration outside the authorized source;
- unauthorized loopback HTTP actions, Host-header bypasses, CSRF-like actions,
  token bypasses, or arbitrary path opening;
- injection through filesystem names into the local dashboard;
- exposure of local path metadata to a remote party;
- packaging or launcher behavior that silently operates outside documented
  boundaries.

Usually out of scope:

- social engineering without a technical flaw;
- vulnerabilities requiring a deliberately modified local source tree and no
  privilege or trust-boundary change;
- denial of service that only stops a developer-preview process and cannot
  affect files;
- unsupported operating systems;
- reports generated only by automated scanners without a concrete impact.

If uncertain, report privately.

## Safe research

Security testing must:

- use only systems and files you own or have explicit permission to test;
- use temporary directories and synthetic data;
- avoid a real Desktop, home directory, Downloads, or Documents tree;
- avoid privacy violations, persistence, destructive testing, or data
  exfiltration;
- stop after establishing the minimum evidence of impact.

The project does not currently offer a bug bounty or authorize testing against
third-party systems.

## Response process

Maintainers aim, on a best-effort basis, to:

1. acknowledge a complete private report within five business days;
2. reproduce and assess severity;
3. coordinate a fix and regression tests;
4. prepare release notes without exposing users prematurely;
5. credit the reporter if they want attribution.

These are targets, not guaranteed response times. Public disclosure should be
coordinated until a fix or reasonable mitigation is available.

## Release security

The repository currently provides source and local developer tooling. An
ad-hoc local signature is not Apple Developer ID signing or notarization.
Official binary distribution must not be claimed until the signing,
notarization, provenance, and release checks in
[docs/release-checklist.md](docs/release-checklist.md) are complete.
