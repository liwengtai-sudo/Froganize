"""Frozen application bootstrap kept intentionally small for PyInstaller."""

from dropnest.macos_app import main


if __name__ == "__main__":
    raise SystemExit(main())
