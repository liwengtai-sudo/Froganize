"""Tests for the source-publication preflight."""

from __future__ import annotations

from pathlib import Path

from scripts.check_public_repo import scan_history_text, scan_paths


def test_public_repo_preflight_accepts_safe_source_and_placeholders(tmp_path: Path) -> None:
    safe = tmp_path / "README.md"
    example_home = "/" + "Users/example/Froganize"
    safe.write_text(f"Try {example_home} and keep data local.\n", encoding="utf-8")

    assert scan_paths(tmp_path, (safe,)) == ()


def test_public_repo_preflight_rejects_personal_paths_without_echoing_them(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "notes.md"
    private_home = "/" + "Users/private-person/Desktop/app"
    unsafe.write_text(f"local checkout: {private_home}\n", encoding="utf-8")

    findings = scan_paths(tmp_path, (unsafe,))

    assert findings == ("personal absolute path: notes.md",)
    assert "private-person" not in findings[0]


def test_public_repo_preflight_rejects_credentials_and_local_history(tmp_path: Path) -> None:
    credential = tmp_path / "config.txt"
    credential.write_text(
        "token=" + "sk-" + "abcdefghijklmnop1234" + "\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.jsonl"
    history.write_text("{}\n", encoding="utf-8")

    findings = scan_paths(tmp_path, (credential, history))

    assert "possible live credential: config.txt" in findings
    assert "credential or local-state filename: history.jsonl" in findings


def test_history_scan_reports_sensitive_classes_without_echoing_values() -> None:
    private_path = "/Users/" + "private-maintainer/secret.txt"
    fake_key = "sk-" + "privateexampletoken123456789"

    findings = scan_history_text(f"+{private_path}\n+API_KEY={fake_key}\n")

    combined = "\n".join(findings)
    assert "personal absolute path" in combined
    assert "possible live credential" in combined
    assert "private-maintainer" not in combined
    assert fake_key not in combined


def test_history_scan_allows_documentation_placeholders() -> None:
    findings = scan_history_text(
        "+/Users/example/Desktop\n+/home/username/project\n"
    )

    assert findings == ()
