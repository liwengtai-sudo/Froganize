"""Private control bridge for the embedded Screenshot Intelligence agent.

The native Qt window never reads the macOS Keychain and never performs an AI
request itself.  It sends one bounded JSON request to the fixed, embedded
Swift executable and accepts one strictly validated JSON response.
"""

from __future__ import annotations

import json
import os
import selectors
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit


CONTROL_SCHEMA_VERSION = 1
MAX_CONTROL_BYTES = 64 * 1024
CONTROL_TIMEOUT_SECONDS = 30.0
CONNECTION_TIMEOUT_SECONDS = 180.0
PROCESS_TIMEOUT_SECONDS = 360.0
SCREENSHOT_CONTROL_RELATIVE_PATH = Path(
    "Contents/Library/LoginItems/FroganizeScreenshotAgent.app/Contents/MacOS/"
    "ScreenshotRenamer"
)
SCREENSHOT_CONTROL_OVERRIDE = "FROGANIZE_SCREENSHOT_CONTROL_BINARY"
CUSTOM_PROVIDER_ID = "customOpenAICompatible"


class IntelligenceControlError(RuntimeError):
    """A concise, user-safe failure from the private control boundary."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ModelOption:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ProviderOption:
    id: str
    name: str
    models: tuple[ModelOption, ...]


@dataclass(frozen=True, slots=True)
class IntelligenceControlState:
    enabled: bool
    upload_consent: bool
    provider: str
    model: str
    folder_path: str
    credential_configured: bool
    credential_source: str | None
    provider_options: tuple[ProviderOption, ...]
    is_working: bool = False
    status_message: str = ""
    last_rename_event_id: str | None = None
    custom_endpoint: str = ""
    custom_model: str = ""


@dataclass(frozen=True, slots=True)
class IntelligenceControlResult:
    message: str
    state: IntelligenceControlState


class IntelligenceController(Protocol):
    def get_state(self) -> IntelligenceControlResult: ...
    def configure_folder(self, folder: Path) -> IntelligenceControlResult: ...
    def set_provider_model(self, provider: str, model: str) -> IntelligenceControlResult: ...
    def configure_custom_provider(
        self, endpoint: str, model: str
    ) -> IntelligenceControlResult: ...
    def set_enabled(self, enabled: bool) -> IntelligenceControlResult: ...
    def save_api_key(self, provider: str, api_key: str) -> IntelligenceControlResult: ...
    def remove_api_key(self, provider: str) -> IntelligenceControlResult: ...
    def test_connection(self, provider: str, model: str) -> IntelligenceControlResult: ...
    def process_latest(self) -> IntelligenceControlResult: ...
    def undo_latest(self) -> IntelligenceControlResult: ...


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise IntelligenceControlError("invalid_response", f"{field} is not a UUID.")
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise IntelligenceControlError("invalid_response", f"{field} is not a UUID.") from exc
    if parsed != value:
        raise IntelligenceControlError(
            "invalid_response", f"{field} is not a canonical lowercase UUID."
        )
    return parsed


def _safe_text(
    value: object,
    field: str,
    *,
    maximum: int = 4096,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str) or "\x00" in value or len(value) > maximum:
        raise IntelligenceControlError("invalid_response", f"{field} is invalid.")
    if not allow_empty and not value.strip():
        raise IntelligenceControlError("invalid_response", f"{field} may not be empty.")
    return value


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise IntelligenceControlError("invalid_response", f"{field} is invalid.")
    return value


def _valid_custom_endpoint(value: str) -> bool:
    if value != value.strip() or len(value.encode("utf-8")) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntelligenceControlError(
                "invalid_response", f"The control response repeats field {key}."
            )
        result[key] = value
    return result


def _contains_forbidden_credential_field(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.casefold()
            if normalized in {
                "api_key",
                "credential",
                "token",
                "authorization",
                "secret",
            }:
                return True
            if _contains_forbidden_credential_field(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_credential_field(item) for item in value)
    return False


def _provider_options(value: object) -> tuple[ProviderOption, ...]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise IntelligenceControlError("invalid_response", "provider_options is invalid.")
    providers: list[ProviderOption] = []
    provider_ids: set[str] = set()
    for raw_provider in value:
        if not isinstance(raw_provider, dict):
            raise IntelligenceControlError("invalid_response", "A provider option is invalid.")
        required = {"id", "name", "models"}
        if not required.issubset(raw_provider):
            raise IntelligenceControlError("invalid_response", "A provider option is incomplete.")
        provider_id = _safe_text(raw_provider["id"], "provider id", maximum=128, allow_empty=False)
        if provider_id in provider_ids:
            raise IntelligenceControlError("invalid_response", "Provider ids are duplicated.")
        provider_ids.add(provider_id)
        raw_models = raw_provider["models"]
        if not isinstance(raw_models, list) or not raw_models or len(raw_models) > 50:
            raise IntelligenceControlError("invalid_response", "Provider models are invalid.")
        models: list[ModelOption] = []
        model_ids: set[str] = set()
        for raw_model in raw_models:
            if not isinstance(raw_model, dict) or not {"id", "name"}.issubset(raw_model):
                raise IntelligenceControlError("invalid_response", "A model option is invalid.")
            model_id = _safe_text(raw_model["id"], "model id", maximum=256, allow_empty=False)
            if model_id in model_ids:
                raise IntelligenceControlError("invalid_response", "Model ids are duplicated.")
            model_ids.add(model_id)
            models.append(
                ModelOption(
                    model_id,
                    _safe_text(raw_model["name"], "model name", maximum=256, allow_empty=False),
                )
            )
        providers.append(
            ProviderOption(
                provider_id,
                _safe_text(raw_provider["name"], "provider name", maximum=256, allow_empty=False),
                tuple(models),
            )
        )
    return tuple(providers)


def _parse_state(value: object) -> IntelligenceControlState:
    if not isinstance(value, dict):
        raise IntelligenceControlError("invalid_response", "The control state is missing.")

    # The alias names are accepted for the first 0.3 development builds.  No
    # credential material is accepted under any name.
    upload_value = value.get("upload_consent")
    if upload_value is None and "consent_version" in value:
        consent_version = value["consent_version"]
        if not isinstance(consent_version, int) or isinstance(consent_version, bool):
            raise IntelligenceControlError("invalid_response", "consent_version is invalid.")
        upload_value = consent_version == 1
    credential_value = value.get("credential_configured", value.get("api_key_configured"))
    credential_source = value.get("credential_source", value.get("api_key_source"))

    required = {"enabled", "provider", "model", "folder_path", "provider_options"}
    if not required.issubset(value) or upload_value is None or credential_value is None:
        raise IntelligenceControlError("invalid_response", "The control state is incomplete.")
    source = None
    if credential_source is not None:
        source = _safe_text(credential_source, "credential_source", maximum=128)
    event_id = value.get("last_rename_event_id")
    if event_id is not None:
        event_id = _canonical_uuid(event_id, "last_rename_event_id")
    providers = _provider_options(value["provider_options"])
    provider_id = _safe_text(value["provider"], "provider", maximum=128, allow_empty=False)
    model_id = _safe_text(value["model"], "model", maximum=256, allow_empty=False)
    selected_provider = next(
        (provider for provider in providers if provider.id == provider_id), None
    )
    if selected_provider is None or model_id not in {
        model.id for model in selected_provider.models
    }:
        raise IntelligenceControlError(
            "invalid_response", "The selected provider or model is not supported."
        )
    folder_path = _safe_text(value["folder_path"], "folder_path", maximum=4096)
    if folder_path and not Path(folder_path).is_absolute():
        raise IntelligenceControlError(
            "invalid_response", "The configured folder path is not absolute."
        )
    custom_endpoint = _safe_text(
        value.get("custom_endpoint", ""), "custom_endpoint", maximum=2048
    )
    if custom_endpoint and not _valid_custom_endpoint(custom_endpoint):
        raise IntelligenceControlError(
            "invalid_response", "The custom provider endpoint is invalid."
        )
    custom_model = _safe_text(
        value.get("custom_model", ""), "custom_model", maximum=256
    )
    if custom_model != custom_model.strip():
        raise IntelligenceControlError(
            "invalid_response", "The custom provider model is invalid."
        )
    return IntelligenceControlState(
        enabled=_bool(value["enabled"], "enabled"),
        upload_consent=_bool(upload_value, "upload_consent"),
        provider=provider_id,
        model=model_id,
        folder_path=folder_path,
        credential_configured=_bool(credential_value, "credential_configured"),
        credential_source=source,
        provider_options=providers,
        is_working=_bool(value.get("is_working", False), "is_working"),
        status_message=_safe_text(value.get("status_message", ""), "status_message"),
        last_rename_event_id=event_id,
        custom_endpoint=custom_endpoint,
        custom_model=custom_model,
    )


def _parse_response(payload: bytes, request_id: str) -> IntelligenceControlResult:
    if not payload or len(payload) > MAX_CONTROL_BYTES:
        raise IntelligenceControlError("invalid_response", "The agent response is empty or too large.")
    try:
        text = payload.decode("utf-8", errors="strict")
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except IntelligenceControlError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntelligenceControlError("invalid_response", "The agent returned malformed JSON.") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != CONTROL_SCHEMA_VERSION:
        raise IntelligenceControlError("invalid_response", "The agent response schema is invalid.")
    if _contains_forbidden_credential_field(raw):
        raise IntelligenceControlError(
            "invalid_response", "The agent returned forbidden credential material."
        )
    if _canonical_uuid(raw.get("request_id"), "request_id") != request_id:
        raise IntelligenceControlError("invalid_response", "The agent response id does not match.")
    status = raw.get("status")
    if status == "error":
        error = raw.get("error")
        if not isinstance(error, dict) or not {"code", "message", "retryable"}.issubset(error):
            raise IntelligenceControlError("invalid_response", "The agent error is invalid.")
        raise IntelligenceControlError(
            _safe_text(error["code"], "error.code", maximum=128, allow_empty=False),
            _safe_text(error["message"], "error.message", maximum=4096, allow_empty=False),
            retryable=_bool(error["retryable"], "error.retryable"),
        )
    if status != "ok":
        raise IntelligenceControlError("invalid_response", "The agent response status is invalid.")
    message = _safe_text(raw.get("message", ""), "message", maximum=4096)
    return IntelligenceControlResult(message, _parse_state(raw.get("state")))


def _contains_symlink(root: Path, candidate: Path) -> bool:
    try:
        if stat.S_ISLNK(root.lstat().st_mode):
            return True
    except OSError:
        return True
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return True
        except OSError:
            return True
    return False


def screenshot_control_binary_path(
    environment: Mapping[str, str],
) -> tuple[Path | None, Path | None]:
    """Return ``(binary, containment_root)`` for packaged or explicit dev use."""
    if getattr(sys, "frozen", False):
        executable = Path(os.path.abspath(sys.executable))
        try:
            bundle = executable.parents[2]
        except IndexError:
            return None, None
        return bundle / SCREENSHOT_CONTROL_RELATIVE_PATH, bundle
    override = environment.get(SCREENSHOT_CONTROL_OVERRIDE)
    if not override:
        return None, None
    candidate = Path(override).expanduser()
    if not candidate.is_absolute():
        return None, None
    return Path(os.path.abspath(candidate)), None


def _validated_binary(binary: Path, containment_root: Path | None) -> Path:
    if not binary.is_absolute():
        raise IntelligenceControlError("control_unavailable", "The agent path is not absolute.")
    if containment_root is not None:
        absolute_root = Path(os.path.abspath(containment_root))
        absolute_binary = Path(os.path.abspath(binary))
        try:
            absolute_binary.relative_to(absolute_root)
        except ValueError as exc:
            raise IntelligenceControlError(
                "control_unavailable", "The embedded agent is outside Froganize."
            ) from exc
        if _contains_symlink(absolute_root, absolute_binary):
            raise IntelligenceControlError(
                "control_unavailable", "The embedded agent path is unsafe."
            )
    try:
        metadata = binary.lstat()
    except OSError as exc:
        raise IntelligenceControlError(
            "control_unavailable", "The Screenshot Intelligence agent is unavailable."
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise IntelligenceControlError("control_unavailable", "The agent executable is unsafe.")
    if not os.access(binary, os.X_OK):
        raise IntelligenceControlError("control_unavailable", "The agent is not executable.")
    return binary


class SubprocessIntelligenceController:
    """Invoke the embedded Swift control service with no shell or network proxy."""

    def __init__(
        self,
        binary: Path,
        *,
        containment_root: Path | None = None,
        timeout: float | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._binary = binary
        self._containment_root = containment_root
        self._timeout = timeout
        self._process_environment = self._safe_child_environment(
            {} if environment is None else environment
        )

    def _timeout_for_action(self, action: str) -> float:
        if self._timeout is not None:
            return self._timeout
        if action == "test_connection":
            return CONNECTION_TIMEOUT_SECONDS
        if action == "process_latest":
            return PROCESS_TIMEOUT_SECONDS
        return CONTROL_TIMEOUT_SECONDS

    @staticmethod
    def _safe_child_environment(selected: Mapping[str, str]) -> dict[str, str]:
        """Build a minimal environment with no provider or dev override secrets."""
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        for name in ("HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME"):
            value = selected.get(name)
            if isinstance(value, str) and value:
                environment[name] = value
        return environment

    @staticmethod
    def _run_bounded(
        executable: Path,
        encoded: bytes,
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> tuple[int, bytes]:
        """Read no more than 64 KiB, including while the child is running."""
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        total = 0
        try:
            process = subprocess.Popen(
                [str(executable), "--control"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                env=dict(environment),
            )
            if process.stdin is None or process.stdout is None:
                raise OSError("control pipes unavailable")
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            sent = 0
            stdout_open = True
            while stdout_open:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        [str(executable), "--control"], timeout
                    )
                events = selector.select(remaining)
                if not events:
                    raise subprocess.TimeoutExpired(
                        [str(executable), "--control"], timeout
                    )
                for key, _mask in events:
                    if key.data == "stdin":
                        try:
                            written = os.write(process.stdin.fileno(), encoded[sent:])
                        except BlockingIOError:
                            continue
                        except (BrokenPipeError, OSError):
                            written = 0
                            sent = len(encoded)
                        else:
                            sent += written
                        if sent >= len(encoded):
                            selector.unregister(process.stdin)
                            try:
                                process.stdin.close()
                            except OSError:
                                pass
                    else:
                        try:
                            chunk = os.read(
                                process.stdout.fileno(),
                                min(8192, MAX_CONTROL_BYTES + 1 - total),
                            )
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(process.stdout)
                            stdout_open = False
                            continue
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > MAX_CONTROL_BYTES:
                            raise IntelligenceControlError(
                                "invalid_response", "The agent response is too large."
                            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(
                    [str(executable), "--control"], timeout
                )
            return process.wait(timeout=remaining), b"".join(chunks)
        finally:
            selector.close()
            if process is not None and process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process is not None and process.stdout is not None and not process.stdout.closed:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            if process is not None and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> SubprocessIntelligenceController | None:
        selected = os.environ if environment is None else environment
        binary, root = screenshot_control_binary_path(selected)
        return (
            None
            if binary is None
            else cls(binary, containment_root=root, environment=selected)
        )

    def _call(self, action: str, **fields: object) -> IntelligenceControlResult:
        request_id = str(uuid.uuid4())
        request = {
            "schema_version": CONTROL_SCHEMA_VERSION,
            "request_id": request_id,
            "action": action,
            **fields,
        }
        try:
            encoded = json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, UnicodeEncodeError) as exc:
            raise IntelligenceControlError("invalid_request", "The control request is invalid.") from exc
        if len(encoded) > MAX_CONTROL_BYTES:
            raise IntelligenceControlError("request_too_large", "The control request is too large.")
        executable = _validated_binary(self._binary, self._containment_root)
        try:
            returncode, stdout = self._run_bounded(
                executable,
                encoded,
                timeout=self._timeout_for_action(action),
                environment=self._process_environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise IntelligenceControlError(
                "control_timeout", "Screenshot Intelligence did not respond in time.", retryable=True
            ) from exc
        except OSError as exc:
            raise IntelligenceControlError(
                "control_unavailable", "Screenshot Intelligence could not be started."
            ) from exc
        if returncode != 0:
            # Do not parse or echo stderr.  A non-zero helper is always fail-closed.
            raise IntelligenceControlError(
                "control_failed", "Screenshot Intelligence failed safely."
            )
        return _parse_response(stdout, request_id)

    def get_state(self) -> IntelligenceControlResult:
        return self._call("get_state")

    def configure_folder(self, folder: Path) -> IntelligenceControlResult:
        candidate = Path(os.path.abspath(folder.expanduser()))
        if (
            not folder.is_absolute()
            or _contains_symlink(Path(candidate.anchor), candidate)
            or not candidate.is_dir()
        ):
            raise IntelligenceControlError("invalid_folder", "Please choose a safe existing folder.")
        return self._call("configure_folder", folder_path=str(candidate))

    def set_provider_model(self, provider: str, model: str) -> IntelligenceControlResult:
        return self._call("set_provider_model", provider=provider, model=model)

    def configure_custom_provider(
        self, endpoint: str, model: str
    ) -> IntelligenceControlResult:
        if not _valid_custom_endpoint(endpoint):
            raise IntelligenceControlError(
                "invalid_endpoint",
                "Please enter a complete HTTPS Chat Completions endpoint.",
            )
        if (
            not model
            or model != model.strip()
            or len(model.encode("utf-8")) > 256
            or any(ord(character) < 32 for character in model)
        ):
            raise IntelligenceControlError(
                "invalid_model", "Please enter a valid model name."
            )
        return self._call(
            "configure_custom_provider", endpoint=endpoint, model=model
        )

    def set_enabled(self, enabled: bool) -> IntelligenceControlResult:
        return self._call(
            "set_enabled", enabled=enabled, consent_version=1 if enabled else 0
        )

    def save_api_key(self, provider: str, api_key: str) -> IntelligenceControlResult:
        if not api_key or len(api_key) > 8192 or "\x00" in api_key:
            raise IntelligenceControlError("invalid_api_key", "Please enter a valid API key.")
        return self._call("save_api_key", provider=provider, api_key=api_key)

    def remove_api_key(self, provider: str) -> IntelligenceControlResult:
        return self._call("remove_api_key", provider=provider)

    def test_connection(self, provider: str, model: str) -> IntelligenceControlResult:
        return self._call("test_connection", provider=provider, model=model)

    def process_latest(self) -> IntelligenceControlResult:
        return self._call("process_latest")

    def undo_latest(self) -> IntelligenceControlResult:
        return self._call("undo_latest")


__all__ = [
    "CONTROL_SCHEMA_VERSION",
    "CUSTOM_PROVIDER_ID",
    "IntelligenceControlError",
    "IntelligenceController",
    "IntelligenceControlResult",
    "IntelligenceControlState",
    "ModelOption",
    "ProviderOption",
    "SCREENSHOT_CONTROL_OVERRIDE",
    "SubprocessIntelligenceController",
    "screenshot_control_binary_path",
]
