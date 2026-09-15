# Third-party notices

Froganize's own source code, documentation, and project-created brand assets
are released under the repository's [MIT License](LICENSE), unless a file says
otherwise.

The source installation can use the following separately distributed Python
packages. They are not relicensed by Froganize:

| Component | Role | Upstream license |
| --- | --- | --- |
| [PySide6 Essentials](https://doc.qt.io/qtforpython-6/) | Optional native macOS interface | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, or a commercial Qt license |
| [PyInstaller](https://pyinstaller.org/) | Optional local application packaging | GPL-2.0-or-later with the PyInstaller bootloader exception |
| [Pillow](https://python-pillow.org/) | Optional deterministic media generation | MIT-CMU |
| [pytest](https://pytest.org/) | Development tests | MIT |
| [build](https://build.pypa.io/) | Python package construction | MIT |
| [setuptools](https://setuptools.pypa.io/) | Build backend | MIT |

The Code of Conduct is adapted from Contributor Covenant 2.1 and retains its
attribution and upstream links in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

The optional Screenshot Intelligence source is included under
`swift/ScreenshotIntelligence/` and uses Apple system frameworks only; it has no
third-party Swift package dependency. Apple frameworks and SDKs remain subject
to Apple's terms. If future Swift dependencies are added, their licenses and
notices must be reviewed here before distribution.
