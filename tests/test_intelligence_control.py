"""Tests for the private Qt-to-Swift Screenshot Intelligence bridge."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

from dropnest.intelligence_control import (
    IntelligenceControlError,
    SCREENSHOT_CONTROL_OVERRIDE,
    SubprocessIntelligenceController,
    screenshot_control_binary_path,
)


def _executable(tmp_path: Path) -> Path:
    binary = tmp_path / "ScreenshotRenamer"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    return binary


def _state() -> dict[str, object]:
    return {
        "enabled": False,
        "upload_consent": False,
        "provider": "customOpenAICompatible",
        "model": "vision-model",
        "folder_path": "",
        "credential_configured": False,
        "credential_source": None,
        "provider_options": [
            {
                "id": "customOpenAICompatible",
                "name": "通用 API",
                "models": [{"id": "vision-model", "name": "vision-model"}],
            }
        ],
        "is_working": False,
        "status_message": "Ready",
        "last_rename_event_id": None,
        "custom_endpoint": "https://example.com/v1/chat/completions",
        "custom_model": "vision-model",
    }


def _successful_run(captured: dict[str, object]):
    def run(executable, encoded, *, timeout, environment):
        request = json.loads(encoded)
        captured.update(
            {
                "executable": executable,
                "timeout": timeout,
                "environment": environment,
                "request": request,
            }
        )
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "ok",
            "message": "Settings loaded.",
            "state": _state(),
        }
        return 0, json.dumps(response).encode("utf-8")

    return run


def test_control_uses_only_stdin_fixed_argument_and_no_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        SubprocessIntelligenceController,
        "_run_bounded",
        staticmethod(_successful_run(captured)),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-in-child-environment")
    controller = SubprocessIntelligenceController(
        binary,
        environment={
            "HOME": str(tmp_path / "home"),
            "OPENAI_API_KEY": "must-not-be-in-child-environment",
            "DYLD_INSERT_LIBRARIES": "/unsafe/library",
            "FROGANIZE_STATE_DIR": "/unsafe/override",
        },
    )

    result = controller.save_api_key(
        "customOpenAICompatible", "stdin-only-secret"
    )

    assert result.message == "Settings loaded."
    assert captured["executable"] == binary
    assert captured["request"]["api_key"] == "stdin-only-secret"  # type: ignore[index]
    assert "stdin-only-secret" not in str(captured["executable"])
    child_environment = captured["environment"]
    assert "OPENAI_API_KEY" not in child_environment
    assert child_environment["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert child_environment["HOME"] == str(tmp_path / "home")
    assert not any(name.startswith(("DYLD_", "LD_", "FROGANIZE_")) for name in child_environment)


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("malformed", "invalid_response"),
        ("nonzero", "control_failed"),
        ("wrong_id", "invalid_response"),
        ("credential_leak", "invalid_response"),
    ],
)
def test_control_fails_closed_for_untrusted_process_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_code: str,
) -> None:
    binary = _executable(tmp_path)

    def run(executable, encoded, *, timeout, environment):
        request = json.loads(encoded)
        if kind == "malformed":
            return 0, b"not-json"
        if kind == "nonzero":
            return 9, b"{}"
        state = _state()
        if kind == "credential_leak":
            state["api_key"] = "must-not-enter-python"
        response = {
            "schema_version": 1,
            "request_id": (
                "00000000-0000-0000-0000-000000000000"
                if kind == "wrong_id"
                else request["request_id"]
            ),
            "status": "ok",
            "message": "ok",
            "state": state,
        }
        return 0, json.dumps(response).encode()

    monkeypatch.setattr(
        SubprocessIntelligenceController, "_run_bounded", staticmethod(run)
    )
    controller = SubprocessIntelligenceController(binary)

    with pytest.raises(IntelligenceControlError) as raised:
        controller.get_state()

    assert raised.value.code == expected_code
    assert "secret stderr" not in str(raised.value)
    assert "must-not-enter-python" not in str(raised.value)


def test_control_timeout_is_retryable_and_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired([str(binary), "--control"], 0.01)

    monkeypatch.setattr(
        SubprocessIntelligenceController, "_run_bounded", staticmethod(timeout)
    )
    controller = SubprocessIntelligenceController(binary, timeout=0.01)

    with pytest.raises(IntelligenceControlError) as raised:
        controller.get_state()

    assert raised.value.code == "control_timeout"
    assert raised.value.retryable is True


def test_error_response_is_validated_and_translated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)

    def run(executable, encoded, *, timeout, environment):
        request = json.loads(encoded)
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "error",
            "error": {
                "code": "credential_missing",
                "message": "Configure an API key first.",
                "retryable": False,
            },
        }
        return 0, json.dumps(response).encode()

    monkeypatch.setattr(
        SubprocessIntelligenceController, "_run_bounded", staticmethod(run)
    )

    with pytest.raises(IntelligenceControlError) as raised:
        SubprocessIntelligenceController(binary).test_connection(
            "customOpenAICompatible", "vision-model"
        )

    assert raised.value.code == "credential_missing"
    assert "Configure an API key" in str(raised.value)


def test_dev_override_must_be_explicit_and_absolute(tmp_path: Path) -> None:
    assert screenshot_control_binary_path({}) == (None, None)
    assert screenshot_control_binary_path(
        {SCREENSHOT_CONTROL_OVERRIDE: "relative/ScreenshotRenamer"}
    ) == (None, None)

    binary = _executable(tmp_path)
    selected, root = screenshot_control_binary_path(
        {SCREENSHOT_CONTROL_OVERRIDE: str(binary)}
    )
    assert selected == binary
    assert root is None


def test_control_rejects_symlink_and_non_executable(tmp_path: Path) -> None:
    target = _executable(tmp_path)
    link = tmp_path / "linked-agent"
    link.symlink_to(target)
    with pytest.raises(IntelligenceControlError, match="unsafe"):
        SubprocessIntelligenceController(link).get_state()

    target.chmod(0o600)
    with pytest.raises(IntelligenceControlError, match="not executable"):
        SubprocessIntelligenceController(target).get_state()


def test_configure_folder_requires_existing_absolute_non_symlink(
    tmp_path: Path,
) -> None:
    controller = SubprocessIntelligenceController(_executable(tmp_path))
    folder = tmp_path / "screenshots"
    folder.mkdir()
    link = tmp_path / "linked-screenshots"
    link.symlink_to(folder, target_is_directory=True)

    with pytest.raises(IntelligenceControlError, match="safe existing"):
        controller.configure_folder(Path("relative"))
    with pytest.raises(IntelligenceControlError, match="safe existing"):
        controller.configure_folder(link)


def test_control_accepts_safe_forward_compatible_state_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)
    captured: dict[str, object] = {}

    def run(executable, encoded, *, timeout, environment):
        request = json.loads(encoded)
        state = _state()
        state["future_safe_status"] = "ignored"
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "ok",
            "message": "ok",
            "state": state,
        }
        captured["request"] = request
        return 0, json.dumps(response).encode()

    monkeypatch.setattr(
        SubprocessIntelligenceController, "_run_bounded", staticmethod(run)
    )
    result = SubprocessIntelligenceController(binary).set_enabled(True)

    assert result.state.upload_consent is False
    assert captured["request"]["consent_version"] == 1  # type: ignore[index]
    assert captured["request"]["enabled"] is True  # type: ignore[index]

    result = SubprocessIntelligenceController(binary).set_enabled(False)
    assert result.state.enabled is False
    assert captured["request"]["consent_version"] == 0  # type: ignore[index]
    assert captured["request"]["enabled"] is False  # type: ignore[index]


def test_control_has_action_specific_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        SubprocessIntelligenceController,
        "_run_bounded",
        staticmethod(_successful_run(captured)),
    )
    controller = SubprocessIntelligenceController(binary)

    controller.get_state()
    assert captured["timeout"] == 30.0
    controller.test_connection("customOpenAICompatible", "vision-model")
    assert captured["timeout"] == 180.0
    controller.process_latest()
    assert captured["timeout"] == 360.0


def test_control_sends_validated_custom_provider_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        SubprocessIntelligenceController,
        "_run_bounded",
        staticmethod(_successful_run(captured)),
    )
    controller = SubprocessIntelligenceController(binary)
    endpoint = "https://example.com/v1/chat/completions"

    controller.configure_custom_provider(endpoint, "vision-model")

    request = captured["request"]
    assert request["action"] == "configure_custom_provider"  # type: ignore[index]
    assert request["endpoint"] == endpoint  # type: ignore[index]
    assert request["model"] == "vision-model"  # type: ignore[index]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/v1/chat/completions",
        "https://user:password@example.com/v1/chat/completions",
        "https://example.com/v1/chat/completions?token=secret",
        "not-a-url",
    ],
)
def test_control_rejects_unsafe_custom_provider_endpoint(
    tmp_path: Path, endpoint: str
) -> None:
    controller = SubprocessIntelligenceController(_executable(tmp_path))

    with pytest.raises(IntelligenceControlError, match="HTTPS"):
        controller.configure_custom_provider(endpoint, "vision-model")


@pytest.mark.parametrize("mutation", ["empty_providers", "wrong_provider", "wrong_model"])
def test_control_cross_validates_current_provider_and_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    binary = _executable(tmp_path)

    def run(executable, encoded, *, timeout, environment):
        request = json.loads(encoded)
        state = _state()
        if mutation == "empty_providers":
            state["provider_options"] = []
        elif mutation == "wrong_provider":
            state["provider"] = "unknown"
        else:
            state["model"] = "unknown-model"
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "ok",
            "message": "ok",
            "state": state,
        }
        return 0, json.dumps(response).encode()

    monkeypatch.setattr(
        SubprocessIntelligenceController, "_run_bounded", staticmethod(run)
    )
    with pytest.raises(IntelligenceControlError, match="provider|model|provider_options"):
        SubprocessIntelligenceController(binary).get_state()


def test_real_process_reader_is_bounded_and_uses_control_argument(tmp_path: Path) -> None:
    binary = tmp_path / "bounded-agent"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "assert sys.argv == [sys.argv[0], '--control']\n"
        "sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(b'x' * (64 * 1024 + 1))\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)

    with pytest.raises(IntelligenceControlError, match="too large"):
        SubprocessIntelligenceController(binary, timeout=5, environment={}).get_state()


def test_real_process_receives_only_selected_safe_environment(tmp_path: Path) -> None:
    binary = tmp_path / "environment-agent"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "sys.stdin.buffer.read()\n"
        "sys.stdout.write(json.dumps(dict(os.environ)))\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)
    selected = {
        "HOME": str(tmp_path / "selected-home"),
        "LANG": "en_US.UTF-8",
        "OPENAI_API_KEY": "never-in-child",
        "DYLD_INSERT_LIBRARIES": "/unsafe/dylib",
        "LD_PRELOAD": "/unsafe/so",
        "FROGANIZE_SCREENSHOT_CONTROL_BINARY": "/unsafe/override",
        "UNRELATED_SECRET": "also-not-allowlisted",
    }
    controller = SubprocessIntelligenceController(binary, environment=selected)

    returncode, payload = controller._run_bounded(
        binary,
        b"{}",
        timeout=5,
        environment=controller._process_environment,
    )
    observed = json.loads(payload)

    assert returncode == 0
    assert observed["HOME"] == selected["HOME"]
    assert observed["LANG"] == selected["LANG"]
    assert observed["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert "OPENAI_API_KEY" not in observed
    assert "DYLD_INSERT_LIBRARIES" not in observed
    assert "LD_PRELOAD" not in observed
    assert "FROGANIZE_SCREENSHOT_CONTROL_BINARY" not in observed
    assert "UNRELATED_SECRET" not in observed


def test_real_process_timeout_kills_and_reaps_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    binary = tmp_path / "sleeping-agent"
    binary.write_text(
        "#!/bin/sh\n"
        f"/bin/echo $$ > {shlex.quote(str(pid_file))}\n"
        "exec /bin/sleep 30\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)

    with pytest.raises(IntelligenceControlError) as raised:
        SubprocessIntelligenceController(
            # macOS may spend more than 200 ms starting a newly-created
            # executable under load.  Give startup enough room while still
            # exercising the controller's bounded timeout and reap path.
            binary, timeout=2.0, environment={}
        ).get_state()

    assert raised.value.code == "control_timeout"
    deadline = time.monotonic() + 2
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
