"""Local-only Desktop web adapter and API tests."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from dropnest.web import DropNestHTTPServer, create_web_server
from dropnest.workspace import initialize_workspace

TOKEN = "test-local-action-token"
DIRECT_OPENER = build_opener(ProxyHandler({}))


@contextmanager
def running_server(
    workspace: Path,
    desktop: Path,
    opened: list[Path] | None = None,
    revealed: list[Path] | None = None,
    trasher: Callable[[Path], None] | None = None,
) -> Iterator[tuple[str, DropNestHTTPServer]]:
    opened_paths = opened if opened is not None else []
    revealed_paths = revealed if revealed is not None else []

    def reject_unexpected_trash(path: Path) -> None:
        raise AssertionError(f"A test attempted to use the real Trash mover: {path}")

    server = create_web_server(
        workspace,
        desktop_path=desktop,
        port=0,
        token=TOKEN,
        opener=opened_paths.append,
        revealer=revealed_paths.append,
        trasher=trasher or reject_unexpected_trash,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str | None = None,
    host: str | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    encoded = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    request = Request(
        base_url + path,
        data=encoded,
        method=method,
        headers={"Accept": "application/json"},
    )
    if method != "GET":
        request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("X-DropNest-Token", token)
    if host is not None:
        request.add_header("Host", host)
    try:
        response = DIRECT_OPENER.open(request, timeout=3)
    except HTTPError as exc:
        payload = json.loads(exc.read())
        return exc.code, payload, dict(exc.headers.items())
    with response:
        payload = json.loads(response.read())
        return response.status, payload, dict(response.headers.items())


def desktop_setup(tmp_path: Path):
    workspace = initialize_workspace(tmp_path / "workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    return workspace, desktop


def old_desktop_file(desktop: Path, name: str = "report.pdf") -> Path:
    source = desktop / name
    source.write_text("web test content", encoding="utf-8")
    timestamp = datetime(2020, 7, 24, 12, 0, tzinfo=UTC).timestamp()
    os.utime(source, (timestamp, timestamp))
    return source


def assess(base_url: str) -> dict[str, Any]:
    status, payload, _ = request_json(
        base_url,
        "/api/assess",
        method="POST",
        token=TOKEN,
    )
    assert status == 200
    return payload["assessment"]


def test_web_assets_health_and_status_are_served_locally(tmp_path: Path) -> None:
    workspace, desktop = desktop_setup(tmp_path)

    with running_server(workspace.root, desktop) as (base_url, _server):
        with DIRECT_OPENER.open(base_url + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
            headers = dict(response.headers.items())
        with DIRECT_OPENER.open(
            base_url + "/froganize-mascot.png",
            timeout=3,
        ) as mascot_response:
            mascot = mascot_response.read()
            mascot_headers = dict(mascot_response.headers.items())
        with DIRECT_OPENER.open(
            base_url + "/favicon.png",
            timeout=3,
        ) as favicon_response:
            favicon = favicon_response.read()
            favicon_headers = dict(favicon_response.headers.items())
        status_code, health, _ = request_json(base_url, "/api/health")
        _, status, _ = request_json(base_url, "/api/status")

    assert response.status == 200
    assert "Froganize" in html
    assert TOKEN in html
    assert 'rel="icon"' in html
    assert 'id="metric-keep"' not in html
    assert 'id="metric-cleanup"' not in html
    assert 'id="more-tools"' in html
    assert 'id="cleanup-count"' in html
    assert 'id="group-cleanup"' in html
    assert 'id="trash-selected"' in html
    assert "建议收起" in html
    assert "超过 7 个完整日" in html
    assert mascot.startswith(b"\x89PNG\r\n\x1a\n")
    assert mascot_headers["Content-Type"] == "image/png"
    assert favicon.startswith(b"\x89PNG\r\n\x1a\n")
    assert favicon_headers["Content-Type"] == "image/png"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert status_code == 200
    assert health["ok"] is True
    assert health["mode"] == "desktop"
    assert status["status"]["valid"] is True
    assert status["status"]["desktop"] == str(desktop)
    assert status["status"]["workspace"] == str(workspace.root)


def test_web_rejects_invalid_host_and_missing_action_token(tmp_path: Path) -> None:
    workspace, desktop = desktop_setup(tmp_path)

    with running_server(workspace.root, desktop) as (base_url, _server):
        invalid_host, host_payload, _ = request_json(
            base_url,
            "/api/status",
            host="example.invalid",
        )
        unauthorized, token_payload, _ = request_json(
            base_url,
            "/api/assess",
            method="POST",
        )

    assert invalid_host == 403
    assert host_payload["error"] == "Invalid local Host header."
    assert unauthorized == 403
    assert token_payload["error"] == "Invalid action token."


def test_web_assessment_is_read_only_and_leaves_old_items_unselected(
    tmp_path: Path,
) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    source = old_desktop_file(desktop)
    history = workspace.history
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert assessment["summary"]["archive"] == 1
    assert assessment["entries"][0]["name"] == "report.pdf"
    assert assessment["entries"][0]["default_selected"] is False
    assert assessment["entries"][0]["selectable"] is True
    assert assessment["entries"][0]["target"].endswith(
        "Timeline/2020/2020-07/report.pdf"
    )
    assert source.read_text(encoding="utf-8") == "web test content"
    assert history.read_text(encoding="utf-8") == ""
    assert before == after


def test_web_cleanup_recommendations_are_unselected_and_action_scoped(
    tmp_path: Path,
) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    cleanup = desktop / "unfinished.crdownload"
    cleanup.write_text("partial", encoding="utf-8")
    old_desktop_file(desktop, "report.pdf")

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)

    by_name = {entry["name"]: entry for entry in assessment["entries"]}
    assert assessment["summary"]["cleanup"] == 1
    assert by_name[cleanup.name]["group"] == "cleanup"
    assert by_name[cleanup.name]["action"] == "trash"
    assert by_name[cleanup.name]["selectable"] is True
    assert by_name[cleanup.name]["default_selected"] is False
    assert by_name["report.pdf"]["action"] == "archive"


def test_web_moves_only_selected_recommendation_to_injected_trash(
    tmp_path: Path,
) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    cleanup = desktop / "unfinished.crdownload"
    cleanup.write_text("partial", encoding="utf-8")
    normal = desktop / "report.pdf"
    normal.write_text("important", encoding="utf-8")
    trash = tmp_path / "Fake Trash"
    trash.mkdir()

    def fake_trash(path: Path) -> None:
        path.rename(trash / path.name)

    with running_server(
        workspace.root,
        desktop,
        trasher=fake_trash,
    ) as (base_url, _server):
        assessment = assess(base_url)
        status, payload, _ = request_json(
            base_url,
            "/api/trash",
            method="POST",
            token=TOKEN,
            body={
                "assessment_id": assessment["assessment_id"],
                "selected": [cleanup.name],
            },
        )

    assert status == 200
    assert payload["batch"]["summary"]["trashed"] == 1
    assert not cleanup.exists()
    assert (trash / cleanup.name).read_text(encoding="utf-8") == "partial"
    assert normal.read_text(encoding="utf-8") == "important"


def test_web_rejects_non_recommended_item_for_trash(tmp_path: Path) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    normal = desktop / "report.pdf"
    normal.write_text("important", encoding="utf-8")

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)
        status, payload, _ = request_json(
            base_url,
            "/api/trash",
            method="POST",
            token=TOKEN,
            body={
                "assessment_id": assessment["assessment_id"],
                "selected": [normal.name],
            },
        )

    assert status == 400
    assert "not in the cleanup recommendation" in payload["error"]
    assert normal.read_text(encoding="utf-8") == "important"


def test_web_archives_only_selected_items_and_undo_restores_desktop(
    tmp_path: Path,
) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    selected = old_desktop_file(desktop, "selected.pdf")
    unselected = old_desktop_file(desktop, "unselected.pdf")
    target = workspace.timeline / "2020/2020-07/selected.pdf"

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)
        archive_status, archived, _ = request_json(
            base_url,
            "/api/archive",
            method="POST",
            token=TOKEN,
            body={
                "assessment_id": assessment["assessment_id"],
                "selected": ["selected.pdf"],
            },
        )
        assert archive_status == 200
        assert archived["batch"]["summary"]["moved"] == 1
        assert not selected.exists()
        assert unselected.read_text(encoding="utf-8") == "web test content"
        assert target.read_text(encoding="utf-8") == "web test content"

        _, status_payload, _ = request_json(base_url, "/api/status")
        undo_status, undone, _ = request_json(
            base_url,
            "/api/undo",
            method="POST",
            token=TOKEN,
        )

    assert status_payload["status"]["latest_moved"] == 1
    assert undo_status == 200
    assert undone["batch"]["summary"]["restored"] == 1
    assert selected.read_text(encoding="utf-8") == "web test content"
    assert not target.exists()


def test_web_assessment_cannot_be_executed_twice(tmp_path: Path) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    old_desktop_file(desktop)

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)
        body = {
            "assessment_id": assessment["assessment_id"],
            "selected": ["report.pdf"],
        }
        first, _, _ = request_json(
            base_url,
            "/api/archive",
            method="POST",
            token=TOKEN,
            body=body,
        )
        second, payload, _ = request_json(
            base_url,
            "/api/archive",
            method="POST",
            token=TOKEN,
            body=body,
        )

    assert first == 200
    assert second == 400
    assert "expired" in payload["error"]


def test_web_opens_only_fixed_folders_and_reveals_assessed_item(
    tmp_path: Path,
) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    source = old_desktop_file(desktop)
    opened: list[Path] = []
    revealed: list[Path] = []

    with running_server(
        workspace.root,
        desktop,
        opened,
        revealed,
    ) as (base_url, _server):
        assessment = assess(base_url)
        desktop_status, _, _ = request_json(
            base_url,
            "/api/open",
            method="POST",
            token=TOKEN,
            body={"target": "desktop"},
        )
        timeline_status, _, _ = request_json(
            base_url,
            "/api/open",
            method="POST",
            token=TOKEN,
            body={"target": "timeline"},
        )
        reveal_status, _, _ = request_json(
            base_url,
            "/api/reveal",
            method="POST",
            token=TOKEN,
            body={
                "assessment_id": assessment["assessment_id"],
                "name": "report.pdf",
            },
        )
        invalid_status, invalid_payload, _ = request_json(
            base_url,
            "/api/open",
            method="POST",
            token=TOKEN,
            body={"target": "../../Desktop"},
        )

    assert desktop_status == 200
    assert timeline_status == 200
    assert reveal_status == 200
    assert opened == [desktop, workspace.timeline]
    assert revealed == [source]
    assert invalid_status == 400
    assert invalid_payload["error"] == (
        "Open target must be 'desktop' or 'timeline'."
    )


def test_web_desktop_mode_does_not_require_inbox(tmp_path: Path) -> None:
    workspace, desktop = desktop_setup(tmp_path)
    workspace.inbox.rmdir()
    old_desktop_file(desktop)

    with running_server(workspace.root, desktop) as (base_url, _server):
        assessment = assess(base_url)

    assert assessment["summary"]["archive"] == 1


@pytest.mark.parametrize("port", (-1, 65536))
def test_web_rejects_invalid_ports(tmp_path: Path, port: int) -> None:
    workspace, desktop = desktop_setup(tmp_path)

    with pytest.raises(ValueError, match="Port must be between"):
        create_web_server(
            workspace.root,
            desktop_path=desktop,
            port=port,
        )
