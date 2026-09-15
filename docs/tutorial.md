# Froganize in one minute

[简体中文](tutorial.zh-CN.md) · [Compatibility demo](../demo/README.md)

> **Source-only macOS beta.** This repository does not currently provide a
> signed or notarized installer. Back up important files before trying any
> file-management tool.

![The current Froganize native dashboard with synthetic files](../media/github/native-dashboard.png)

Froganize collects every safely movable item from the top level of Desktop and
files it by modification month under `Timeline/YYYY/YYYY-MM/`. Opening the app
never moves anything.

## 1. Install from source

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,gui]"
```

Requirements: macOS and Python 3.11 or newer. The native UI is currently tested
on Apple Silicon.

## 2. Open Froganize

```bash
python -m dropnest.macos_app
```

The app creates or reuses a local workspace in Documents, assesses only direct
Desktop children, and shows what can move and what must remain. This assessment
reads filesystem metadata only; it does not read document contents.

macOS may request Desktop-folder access on first use. Grant it only if you want
Froganize to assess and collect Desktop items.

## 3. Review the assessment

- Safe regular files and complete folders are ready to collect.
- Hidden items, temporary files, incomplete downloads, symbolic links,
  applications, and anything unsafe stay in place with a reason.
- A folder is always one whole item; Froganize never splits its contents.

Files use `st_mtime`. Folders use the newest modification time found in their
readable tree. Creation time and the current click time are not used.

## 4. Press **Collect Desktop**

One press authorizes the exact assessment currently shown. Each safe item moves
to its own modification month:

```text
Desktop/report.pdf  →  Timeline/2026/2026-07/report.pdf
```

Items from different months share one history batch. Existing names are never
overwritten; Froganize allocates names such as `report (1).pdf` instead.

## 5. Review or undo

Open **Organization Calendar** to see operation dates, batch details, original
names, and destinations. Froganize can undo the latest outstanding successful
Desktop batch. Missing destinations and occupied original paths are reported,
never overwritten.

## Optional Screenshot Intelligence

Screenshot Intelligence is experimental, off by default, and uses your own
compatible AI provider credentials. Its complete Swift background source is in
`swift/ScreenshotIntelligence/`. The organizer, calendar, and undo flow do not
require AI or a network connection.

## Practice without using your Desktop

Use the [synthetic compatibility demo](../demo/README.md). It creates disposable
files in a temporary directory and demonstrates retained safety, conflict, and
undo behavior without touching your real Desktop.

The daily loop is simply: **open → review → Collect Desktop → done**.
