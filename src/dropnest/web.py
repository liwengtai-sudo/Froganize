"""Local-only Desktop assessment dashboard for DropNest."""

from __future__ import annotations

import hmac
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from dropnest import __version__
from dropnest.cleanup import (
    TrashMover,
    execute_cleanup_recommendations,
    move_to_macos_trash,
)
from dropnest.exceptions import DropNestError
from dropnest.models import (
    BatchResult,
    DesktopAssessment,
    EvaluationGroup,
    OperationStatus,
    PlanStatus,
    StatusReport,
)
from dropnest.planner import build_desktop_assessment
from dropnest.sorter import execute_selected_plan, undo_workspace
from dropnest.status import inspect_status
from dropnest.workspace import validate_desktop_source, validate_workspace

_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_MAX_REQUEST_BYTES = 65_536
_ASSET_TYPES = {
    "app.js": "text/javascript; charset=utf-8",
    "favicon.png": "image/png",
    "froganize-mascot.png": "image/png",
    "styles.css": "text/css; charset=utf-8",
}

JsonObject = dict[str, Any]
PathOpener = Callable[[Path], None]


@dataclass(slots=True)
class WebApplication:
    """Fixed local paths and one short-lived assessment capability."""

    workspace: Path
    desktop: Path
    token: str
    opener: PathOpener
    revealer: PathOpener
    trasher: TrashMover
    debug: bool = False
    _assessment_id: str | None = None
    _assessment: DesktopAssessment | None = None
    _assessment_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def store_assessment(self, assessment: DesktopAssessment) -> str:
        assessment_id = secrets.token_urlsafe(24)
        with self._assessment_lock:
            self._assessment_id = assessment_id
            self._assessment = assessment
        return assessment_id

    def get_assessment(self, assessment_id: str) -> DesktopAssessment:
        with self._assessment_lock:
            if (
                not assessment_id
                or self._assessment_id is None
                or not hmac.compare_digest(assessment_id, self._assessment_id)
                or self._assessment is None
            ):
                raise ValueError(
                    "This Desktop assessment has expired. Assess the Desktop again."
                )
            return self._assessment

    def claim_assessment(self, assessment_id: str) -> DesktopAssessment:
        with self._assessment_lock:
            if (
                not assessment_id
                or self._assessment_id is None
                or not hmac.compare_digest(assessment_id, self._assessment_id)
                or self._assessment is None
            ):
                raise ValueError(
                    "This Desktop assessment has expired. Assess the Desktop again."
                )
            assessment = self._assessment
            self._assessment_id = None
            self._assessment = None
            return assessment

    def clear_assessment(self) -> None:
        with self._assessment_lock:
            self._assessment_id = None
            self._assessment = None


class DropNestHTTPServer(ThreadingHTTPServer):
    """Threaded loopback server carrying one immutable path scope."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        application: WebApplication,
    ) -> None:
        self.application = application
        super().__init__(server_address, DropNestRequestHandler)


def _default_folder_opener(path: Path) -> None:
    if sys.platform != "darwin":
        raise OSError("Opening folders is currently supported only on macOS.")
    subprocess.run(["open", str(path)], check=True)


def _default_item_revealer(path: Path) -> None:
    if sys.platform != "darwin":
        raise OSError("Revealing files is currently supported only on macOS.")
    subprocess.run(["open", "-R", str(path)], check=True)


def _status_payload(report: StatusReport, desktop: Path) -> JsonObject:
    return {
        "workspace": str(report.workspace),
        "desktop": str(desktop),
        "valid": report.workspace_valid,
        "archive_months": report.archive_month_count,
        "latest_batch_id": report.latest_batch_id,
        "latest_sort_time": report.latest_sort_time,
        "latest_moved": report.latest_moved_count,
        "latest_undo": report.latest_undo_status,
        "config_valid": report.config_valid,
        "history_valid": report.history_valid,
        "problems": list(report.problems),
    }


def _assessment_payload(
    assessment_id: str,
    assessment: DesktopAssessment,
) -> JsonObject:
    entries: list[JsonObject] = []
    for assessed in assessment.entries:
        entry = assessed.plan_entry
        cleanup_candidate = assessed.group is EvaluationGroup.CLEANUP
        archive_candidate = entry.status is PlanStatus.PLANNED
        entries.append(
            {
                "name": entry.source.name,
                "source": str(entry.source),
                "target": str(entry.target) if entry.target else None,
                "item_type": entry.item_type.value if entry.item_type else None,
                "status": entry.status.value,
                "group": assessed.group.value,
                "age_days": assessed.age_days,
                "default_selected": assessed.default_selected,
                "selectable": cleanup_candidate or archive_candidate,
                "action": (
                    "trash"
                    if cleanup_candidate
                    else "archive" if archive_candidate else None
                ),
                "classification_time": (
                    entry.classification_time.isoformat()
                    if entry.classification_time
                    else None
                ),
                "renamed_from": entry.renamed_from,
                "reason_code": entry.reason_code,
                "reason": entry.reason,
            }
        )
    return {
        "assessment_id": assessment_id,
        "generated_at": assessment.plan.generated_at.isoformat(),
        "desktop": str(assessment.plan.source_root),
        "archive": str(assessment.plan.workspace.timeline),
        "entries": entries,
        "summary": {
            group.value: assessment.count(group)
            for group in EvaluationGroup
        },
    }


def _batch_payload(batch: BatchResult) -> JsonObject:
    return {
        "batch_id": batch.batch_id,
        "results": [
            {
                "name": result.source.name,
                "source": str(result.source),
                "target": str(result.target) if result.target else None,
                "status": result.status.value,
                "reason_code": result.reason_code,
                "reason": result.reason,
            }
            for result in batch.results
        ],
        "summary": {
            "moved": batch.count(OperationStatus.MOVED),
            "trashed": batch.count(OperationStatus.TRASHED),
            "restored": batch.count(OperationStatus.RESTORED),
            "skipped": batch.count(OperationStatus.SKIPPED),
            "failed": batch.count(OperationStatus.FAILED),
        },
    }


def _asset_bytes(name: str, token: str) -> bytes:
    asset = resources.files("dropnest").joinpath("web_assets", name)
    data = asset.read_bytes()
    if name == "index.html":
        data = data.replace(b"__DROPNEST_TOKEN__", token.encode("ascii"))
    return data


def _selected_names(
    payload: JsonObject,
    *,
    action_label: str,
) -> tuple[str, ...]:
    raw = payload.get("selected")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Select at least one Desktop item to {action_label}.")
    if len(raw) > 10_000:
        raise ValueError("Too many Desktop items were selected.")
    names: list[str] = []
    for value in raw:
        if (
            not isinstance(value, str)
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\0" in value
        ):
            raise ValueError("Selected Desktop item names are invalid.")
        names.append(value)
    if len(names) != len(set(names)):
        raise ValueError("Selected Desktop item names must be unique.")
    return tuple(names)


class DropNestRequestHandler(BaseHTTPRequestHandler):
    """Serve static assets and a deliberately small same-origin JSON API."""

    server: DropNestHTTPServer
    server_version = "DropNestLocal"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        if self.server.application.debug:
            super().log_message(format, *args)

    def _host_is_allowed(self) -> bool:
        host_header = self.headers.get("Host", "")
        host = host_header.rsplit(":", 1)[0].lower()
        return host in {_LOOPBACK_HOST, "localhost"}

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'",
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
    ) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: JsonObject) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, encoded, "application/json; charset=utf-8")

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def _authorize_host(self) -> bool:
        if self._host_is_allowed():
            return True
        self._send_error_json(HTTPStatus.FORBIDDEN, "Invalid local Host header.")
        return False

    def _authorize_action(self) -> bool:
        supplied = self.headers.get("X-DropNest-Token", "")
        expected = self.server.application.token
        if supplied and hmac.compare_digest(supplied, expected):
            return True
        self._send_error_json(HTTPStatus.FORBIDDEN, "Invalid action token.")
        return False

    def _read_json(self) -> JsonObject:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length < 0 or length > _MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large.")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def do_GET(self) -> None:
        if not self._authorize_host():
            return
        if self.path == "/":
            body = _asset_bytes("index.html", self.server.application.token)
            self._send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8")
            return
        if self.path in {
            "/app.js",
            "/favicon.png",
            "/froganize-mascot.png",
            "/styles.css",
        }:
            name = self.path.removeprefix("/")
            self._send_bytes(
                HTTPStatus.OK,
                _asset_bytes(name, self.server.application.token),
                _ASSET_TYPES[name],
            )
            return
        if self.path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "version": __version__, "mode": "desktop"},
            )
            return
        if self.path == "/api/status":
            application = self.server.application
            report = inspect_status(
                application.workspace,
                source_path=application.desktop,
                scan_source=False,
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": _status_payload(report, application.desktop),
                },
            )
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self) -> None:
        if not self._authorize_host() or not self._authorize_action():
            return
        try:
            payload = self._read_json()
            response = self._perform_action(payload)
        except (DropNestError, OSError, ValueError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self.log_error("Unhandled local web error: %s", exc)
            message = str(exc) if self.server.application.debug else "Unexpected error."
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, message)
            return
        self._send_json(HTTPStatus.OK, {"ok": True, **response})

    def _perform_action(self, payload: JsonObject) -> JsonObject:
        application = self.server.application
        if self.path == "/api/assess":
            assessment = build_desktop_assessment(
                application.workspace,
                desktop_path=application.desktop,
            )
            assessment_id = application.store_assessment(assessment)
            return {
                "assessment": _assessment_payload(
                    assessment_id,
                    assessment,
                )
            }
        if self.path == "/api/archive":
            assessment_id = payload.get("assessment_id")
            if not isinstance(assessment_id, str):
                raise ValueError("A valid Desktop assessment is required.")
            selected = _selected_names(payload, action_label="archive")
            assessment = application.claim_assessment(assessment_id)
            batch = execute_selected_plan(assessment.plan, selected)
            return {"batch": _batch_payload(batch)}
        if self.path == "/api/trash":
            assessment_id = payload.get("assessment_id")
            if not isinstance(assessment_id, str):
                raise ValueError("A valid Desktop assessment is required.")
            selected = _selected_names(payload, action_label="move to Trash")
            assessment = application.claim_assessment(assessment_id)
            batch = execute_cleanup_recommendations(
                assessment,
                selected,
                trash_mover=application.trasher,
            )
            return {"batch": _batch_payload(batch)}
        if self.path == "/api/undo":
            application.clear_assessment()
            batch = undo_workspace(
                application.workspace,
                source_root=application.desktop,
            )
            return {"batch": _batch_payload(batch)}
        if self.path == "/api/open":
            target_name = payload.get("target")
            workspace = validate_workspace(
                application.workspace,
                require_inbox=False,
            )
            targets = {
                "desktop": application.desktop,
                "timeline": workspace.timeline,
            }
            if target_name not in targets:
                raise ValueError("Open target must be 'desktop' or 'timeline'.")
            target = targets[target_name]
            application.opener(target)
            return {"opened": str(target)}
        if self.path == "/api/reveal":
            assessment_id = payload.get("assessment_id")
            name = payload.get("name")
            if not isinstance(assessment_id, str) or not isinstance(name, str):
                raise ValueError("A current assessment and item name are required.")
            assessment = application.get_assessment(assessment_id)
            allowed_names = {
                entry.plan_entry.source.name
                for entry in assessment.entries
            }
            if name not in allowed_names:
                raise ValueError("Desktop item is not in the current assessment.")
            target = application.desktop / name
            if target.parent != application.desktop or not target.exists():
                raise ValueError("Desktop item no longer exists.")
            application.revealer(target)
            return {"revealed": str(target)}
        raise ValueError("Unknown action.")


def create_web_server(
    workspace_path: str | Path,
    *,
    desktop_path: str | Path | None = None,
    port: int = _DEFAULT_PORT,
    token: str | None = None,
    opener: PathOpener = _default_folder_opener,
    revealer: PathOpener = _default_item_revealer,
    trasher: TrashMover = move_to_macos_trash,
    debug: bool = False,
) -> DropNestHTTPServer:
    """Create a validated loopback server without starting its event loop."""
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    workspace = validate_workspace(workspace_path, require_inbox=False)
    desktop = validate_desktop_source(
        desktop_path or (Path.home() / "Desktop"),
        workspace,
    )
    application = WebApplication(
        workspace=workspace.root,
        desktop=desktop,
        token=token or secrets.token_urlsafe(32),
        opener=opener,
        revealer=revealer,
        trasher=trasher,
        debug=debug,
    )
    return DropNestHTTPServer((_LOOPBACK_HOST, port), application)


def run_web(
    workspace_path: str | Path,
    *,
    desktop_path: str | Path | None = None,
    port: int = _DEFAULT_PORT,
    open_browser: bool = True,
    debug: bool = False,
) -> None:
    """Run the local Desktop dashboard until interrupted by the user."""
    server = create_web_server(
        workspace_path,
        desktop_path=desktop_path,
        port=port,
        debug=debug,
    )
    actual_port = server.server_address[1]
    url = f"http://{_LOOPBACK_HOST}:{actual_port}/"
    print("Froganize Desktop dashboard.")
    print(f"Desktop: {server.application.desktop}")
    print(f"Timeline: {server.application.workspace / 'Timeline'}")
    print(f"Open: {url}")
    print("Press Ctrl-C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nFroganize dashboard stopped.")
    finally:
        server.server_close()
