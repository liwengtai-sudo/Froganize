"""Offscreen checks for the native Froganize Qt interface."""

from __future__ import annotations

import os
import stat
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox

from dropnest.desktop_app import DesktopApplication
from dropnest.gui import FroganizeWindow, _vector_mascot
from dropnest.intelligence_control import (
    IntelligenceControlResult,
    IntelligenceControlState,
    ModelOption,
    ProviderOption,
)
from dropnest.intelligence_contract import ScreenshotAnalysis, ScreenshotSnapshot
from dropnest.intelligence_history import (
    IntelligencePaths,
    append_activity,
    new_rename_record,
    write_config,
)
from dropnest.workspace import initialize_workspace


@pytest.fixture(autouse=True)
def _isolate_default_intelligence_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "FROGANIZE_STATE_DIR", str(tmp_path / "isolated-intelligence-state")
    )


def _qt_app() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


def _wait_until(predicate, timeout: float = 4.0) -> None:
    app = _qt_app()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Qt interface.")


def _setup(tmp_path: Path) -> tuple[DesktopApplication, Path, Path]:
    workspace = initialize_workspace(tmp_path / "Workspace").workspace
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    old = desktop / "old report.pdf"
    old.write_text("old", encoding="utf-8")
    timestamp = datetime(2020, 7, 24, 12, 0, tzinfo=UTC).timestamp()
    os.utime(old, (timestamp, timestamp))
    recent = desktop / "recent.txt"
    recent.write_text("recent", encoding="utf-8")
    recent_timestamp = datetime(2026, 8, 15, 12, 0, tzinfo=UTC).timestamp()
    os.utime(recent, (recent_timestamp, recent_timestamp))
    cleanup = desktop / "unfinished.crdownload"
    cleanup.write_text("partial", encoding="utf-8")
    hidden = desktop / ".hidden"
    hidden.write_text("keep", encoding="utf-8")
    backend = DesktopApplication.create(
        workspace.root,
        desktop_path=desktop,
        opener=lambda _path: None,
        revealer=lambda _path: None,
        trasher=lambda _path: None,
    )
    return backend, workspace.root, desktop


def test_all_native_mascot_variants_render_as_retina_svg() -> None:
    _qt_app()
    for name in (
        "froganize-idle.svg",
        "froganize-organizing.svg",
        "froganize-calendar.svg",
        "froganize-success.svg",
    ):
        mascot = _vector_mascot(name, 64)
        assert not mascot.isNull()
        assert mascot.width() == 128
        assert mascot.height() == 128
        assert mascot.devicePixelRatio() == 2


class _FakeIntelligenceController:
    def __init__(self, folder: Path) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.saved_key: str | None = None
        self.state = IntelligenceControlState(
            enabled=False,
            upload_consent=False,
            provider="customOpenAICompatible",
            model="vision-model",
            folder_path=str(folder),
            credential_configured=True,
            credential_source="Keychain",
            provider_options=(
                ProviderOption(
                    "customOpenAICompatible",
                    "通用 API",
                    (ModelOption("vision-model", "vision-model"),),
                ),
            ),
            custom_endpoint="https://example.com/v1/chat/completions",
            custom_model="vision-model",
            status_message="Ready",
            last_rename_event_id=str(uuid.uuid4()),
        )

    def _result(self, message: str) -> IntelligenceControlResult:
        return IntelligenceControlResult(message, self.state)

    def get_state(self) -> IntelligenceControlResult:
        self.calls.append(("get_state",))
        return self._result("Settings loaded")

    def configure_folder(self, folder: Path) -> IntelligenceControlResult:
        self.calls.append(("configure_folder", folder))
        self.state = replace(self.state, folder_path=str(folder))
        return self._result("Folder configured")

    def set_provider_model(self, provider: str, model: str) -> IntelligenceControlResult:
        self.calls.append(("set_provider_model", provider, model))
        self.state = replace(self.state, provider=provider, model=model)
        return self._result("Model saved")

    def configure_custom_provider(
        self, endpoint: str, model: str
    ) -> IntelligenceControlResult:
        self.calls.append(("configure_custom_provider", endpoint, model))
        self.state = replace(
            self.state,
            provider="customOpenAICompatible",
            model=model,
            custom_endpoint=endpoint,
            custom_model=model,
            provider_options=tuple(
                replace(option, models=(ModelOption(model, model),))
                if option.id == "customOpenAICompatible"
                else option
                for option in self.state.provider_options
            ),
        )
        return self._result("Custom provider saved")

    def set_enabled(self, enabled: bool) -> IntelligenceControlResult:
        self.calls.append(("set_enabled", enabled))
        self.state = replace(
            self.state, enabled=enabled, upload_consent=enabled
        )
        return self._result("Enabled" if enabled else "Disabled")

    def save_api_key(self, provider: str, api_key: str) -> IntelligenceControlResult:
        self.calls.append(("save_api_key", provider))
        self.saved_key = api_key
        self.state = replace(
            self.state, credential_configured=True, credential_source="Keychain"
        )
        return self._result("Key saved")

    def remove_api_key(self, provider: str) -> IntelligenceControlResult:
        self.calls.append(("remove_api_key", provider))
        self.saved_key = None
        self.state = replace(
            self.state, credential_configured=False, credential_source=None
        )
        return self._result("Key removed")

    def test_connection(self, provider: str, model: str) -> IntelligenceControlResult:
        self.calls.append(("test_connection", provider, model))
        return self._result("Connection works")

    def process_latest(self) -> IntelligenceControlResult:
        self.calls.append(("process_latest",))
        return self._result("Latest screenshot renamed")

    def undo_latest(self) -> IntelligenceControlResult:
        self.calls.append(("undo_latest",))
        self.state = replace(self.state, last_rename_event_id=None)
        return self._result("Screenshot rename undone")


def test_window_summarizes_one_click_collection_without_item_selection(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()

    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)

    assert window.windowTitle() == "Froganize"
    assert "2 项" in window.summary.text()
    assert "2 项因安全规则留在原位" in window.collection_note.text()
    assert window.collect_button.isEnabled()
    assert "收好桌面" in window.collect_button.text()
    assert "最后修改年月" in window.desktop_subtitle.text()
    window.close()
    app.processEvents()


def test_one_click_collects_every_safe_item_into_one_batch(tmp_path: Path) -> None:
    app = _qt_app()
    backend, workspace, desktop = _setup(tmp_path)
    confirmations: list[tuple[str, str]] = []
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        confirm=lambda title, body: confirmations.append((title, body)) or False,
    )
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)

    window.collect_button.click()
    _wait_until(lambda: not window._busy and not (desktop / "old report.pdf").exists())

    assert (workspace / "Timeline/2020/2020-07/old report.pdf").read_text(
        encoding="utf-8"
    ) == "old"
    assert (workspace / "Timeline/2026/2026-08/recent.txt").read_text(
        encoding="utf-8"
    ) == "recent"
    assert (desktop / "unfinished.crdownload").exists()
    assert (desktop / ".hidden").exists()
    assert confirmations == []
    assert "整理魔法完成" in window.result_banner.text()
    window.close()
    app.processEvents()


def test_collect_button_ignores_a_second_click_while_busy(tmp_path: Path) -> None:
    app = _qt_app()
    backend, workspace, desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)

    window._collect_all()
    window._collect_all()
    _wait_until(lambda: not window._busy and not (desktop / "old report.pdf").exists())

    assert (workspace / "Timeline/2020/2020-07/old report.pdf").exists()
    assert (workspace / "Timeline/2026/2026-08/recent.txt").exists()
    window.close()
    app.processEvents()


def test_one_click_undo_restores_the_latest_collection(tmp_path: Path) -> None:
    app = _qt_app()
    backend, _workspace, desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)

    window._collect_all()
    _wait_until(lambda: not window._busy and not (desktop / "old report.pdf").exists())
    window._undo()
    _wait_until(lambda: not window._busy and (desktop / "old report.pdf").exists())

    assert (desktop / "old report.pdf").exists()
    assert (desktop / "recent.txt").exists()
    assert "放回桌面" in window.result_banner.text()
    window.close()
    app.processEvents()


def test_history_calendar_shows_collections_on_their_operation_day(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)
    window._collect_all()
    _wait_until(
        lambda: not window._busy and not (desktop / "old report.pdf").exists()
    )

    window.history_nav.click()
    _wait_until(
        lambda: not window._busy
        and window._history_calendar is not None
        and bool(window._history_calendar.batches)
    )

    latest = window._history_calendar.batches[0]
    latest_day = latest.occurred_at.date()
    marked = [
        button
        for button in window.history_day_buttons
        if button.property("calendarDate") == latest_day.isoformat()
    ]
    details = "\n".join(
        label.text()
        for label in window.history_detail_scroll.widget().findChildren(QLabel)
    )
    assert window.pages.currentIndex() == 1
    assert len(marked) == 1
    assert marked[0].property("hasHistory") is True
    assert "2 项" in marked[0].text()
    assert "old report.pdf" in details
    assert "Timeline/2020/2020-07/old report.pdf" in details
    assert window.history_undo_button.isEnabled()
    assert "撤销最近整理" in window.history_undo_button.text()
    window.close()
    app.processEvents()


def test_history_calendar_reviews_then_undoes_only_after_confirmation(
    tmp_path: Path,
) -> None:
    decisions = iter((False, True))
    app = _qt_app()
    backend, _workspace, desktop = _setup(tmp_path)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        confirm=lambda _title, _body: next(decisions),
    )
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)
    window._collect_all()
    _wait_until(
        lambda: not window._busy and not (desktop / "old report.pdf").exists()
    )
    window.history_nav.click()
    _wait_until(
        lambda: not window._busy
        and window._history_calendar is not None
        and window.history_undo_button.isEnabled()
    )

    window.history_undo_button.click()
    app.processEvents()
    assert not (desktop / "old report.pdf").exists()

    window.history_undo_button.click()
    _wait_until(
        lambda: not window._busy
        and (desktop / "old report.pdf").exists()
        and window._history_calendar is not None
        and window._history_calendar.latest_undoable_batch_id is None
    )

    assert not window.history_undo_button.isEnabled()
    assert "蛙仔已把 2 项放回桌面" in window.history_result.text()
    window.close()
    app.processEvents()


def test_history_calendar_reports_damaged_history_without_mutation(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, workspace, desktop = _setup(tmp_path)
    history = workspace / ".dropnest/history.jsonl"
    history.write_text("{damaged\n", encoding="utf-8")
    before = sorted(path.name for path in desktop.iterdir())
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()

    window.history_nav.click()
    _wait_until(lambda: not window._busy and window.history_result.isVisible())

    assert "无法读取整理记录" in window.history_result.text()
    assert not window.history_undo_button.isEnabled()
    assert sorted(path.name for path in desktop.iterdir()) == before
    window.close()
    app.processEvents()


def test_undo_conflict_does_not_claim_there_is_nothing_to_undo(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)

    window._collect_all()
    _wait_until(lambda: not window._busy and not (desktop / "old report.pdf").exists())
    (desktop / "old report.pdf").write_text("conflict", encoding="utf-8")
    (desktop / "recent.txt").write_text("conflict", encoding="utf-8")
    window._undo()
    _wait_until(lambda: not window._busy)

    assert "没有成功放回桌面" in window.result_banner.text()
    assert "没有可以撤销" not in window.result_banner.text()
    window.close()
    app.processEvents()


def test_open_collection_restores_story_copy_after_finder_returns(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    window.show()
    window.refresh_assessment()
    _wait_until(lambda: not window._busy and window._assessment is not None)
    expected = window.desktop_subtitle.text()

    window._open_folder("timeline")
    _wait_until(lambda: not window._busy)

    assert window.desktop_subtitle.text() == expected
    window.close()
    app.processEvents()


def test_native_confirmation_accepts_integer_ok_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PySide6 may return a plain int from the native macOS question box."""
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    window = FroganizeWindow(backend, auto_assess=False)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: int(QMessageBox.Ok),
    )

    assert window._ask("确认收起", "测试") is True

    window.close()
    app.processEvents()


def test_screenshot_intelligence_uses_injected_state_and_launcher(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    paths = IntelligencePaths.from_root(tmp_path / "intelligence-state")
    agent = tmp_path / "FroganizeScreenshotAgent.app"
    agent.mkdir()
    launched: list[Path] = []
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        environment={"FROGANIZE_SCREENSHOT_AGENT_APP": str(agent)},
        intelligence_paths=paths,
        screenshot_launcher=launched.append,
    )

    assert window.intelligence_configuration.text() == "尚未配置截图目录"
    assert "不代表后台组件是否正在运行" in window.intelligence_runtime_note.text()
    assert not paths.root.exists()
    assert window.open_intelligence_button.isEnabled()

    window.open_intelligence_button.click()
    app.processEvents()

    assert launched == [agent.resolve()]
    assert window.intelligence_launch_message.text() == "已向 macOS 发送打开请求。"
    assert not paths.root.exists()
    window.close()
    app.processEvents()


def test_screenshot_intelligence_projects_history_and_read_errors(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    paths = IntelligencePaths.from_root(tmp_path / "intelligence-state")
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    request_id = str(uuid.uuid4())
    fingerprint = "a" * 64
    write_config(
        paths,
        screenshot_root=screenshots,
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    record = new_rename_record(
        request_id=str(uuid.uuid4()),
        request_fingerprint="b" * 64,
        source_root=screenshots,
        original_name="Screenshot.png",
        renamed_name="Froganize-配置页.png",
        snapshot=ScreenshotSnapshot(
            device=1,
            inode=2,
            mode=stat.S_IFREG | 0o600,
            size=10,
            mtime_ns=123,
        ),
        analysis=ScreenshotAnalysis(
            title="Froganize 配置页",
            summary="一张配置页截图。",
            category="图片",
            confidence=0.9,
            sensitive=False,
        ),
        provider="test",
        model="fake",
    )
    append_activity(paths, record)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_paths=paths,
        screenshot_launcher=lambda _path: None,
    )

    assert str(screenshots) in window.intelligence_configuration.text()
    assert "Froganize-配置页.png" in window.intelligence_activity.text()
    assert record.timestamp in window.intelligence_activity.text()
    assert window.intelligence_undo.text() == "当前可撤销：1 项"
    assert "最近活动" in window.intelligence_recent_activity.text()
    assert "Screenshot.png → Froganize-配置页.png" in window.intelligence_recent_activity.text()
    assert window.intelligence_problem.isHidden()

    paths.activity.write_text("{damaged\n", encoding="utf-8")
    window.refresh_intelligence_status()

    assert "状态需要注意" in window.intelligence_problem.text()
    assert not window.intelligence_problem.isHidden()
    window.close()
    app.processEvents()


def test_screenshot_intelligence_complete_panel_uses_injected_controller(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    old_folder = tmp_path / "Old Screenshots"
    old_folder.mkdir()
    new_folder = tmp_path / "New Screenshots"
    new_folder.mkdir()
    fake = _FakeIntelligenceController(old_folder)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
        folder_picker=lambda _parent, _current: new_folder,
    )
    window.show()

    window.refresh_intelligence_control()
    _wait_until(lambda: not window._intelligence_busy and window._intelligence_state is not None)
    assert "允许上传并启用" in window.intelligence_enabled.text()

    assert window.intelligence_folder.text() == str(old_folder)
    assert window.intelligence_custom_endpoint.text() == (
        "https://example.com/v1/chat/completions"
    )
    assert window.intelligence_custom_model.text() == "vision-model"
    assert window.intelligence_api_key.echoMode() is QLineEdit.EchoMode.Password
    assert "Keychain" in window.intelligence_credential.text()
    assert not window.intelligence_enabled.isChecked()
    assert not window.intelligence_process_latest.isEnabled()

    window.intelligence_choose_folder.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert ("configure_folder", new_folder) in fake.calls
    assert window.intelligence_folder.text() == str(new_folder)

    window.intelligence_api_key.setText("test-key-visible-only-to-fake")
    window.intelligence_save_key.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert fake.saved_key == "test-key-visible-only-to-fake"
    assert window.intelligence_api_key.text() == ""
    assert not window.intelligence_api_key.isUndoAvailable()
    window.intelligence_api_key.undo()
    assert window.intelligence_api_key.text() == ""
    assert all("test-key-visible-only-to-fake" not in repr(call) for call in fake.calls)

    window.intelligence_test_connection.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert (
        "test_connection",
        "customOpenAICompatible",
        "vision-model",
    ) in fake.calls

    window.intelligence_consent.setChecked(True)
    window.intelligence_enabled.setChecked(True)
    _wait_until(lambda: not window._intelligence_busy)
    assert window.intelligence_process_latest.isEnabled()
    window.intelligence_process_latest.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert ("process_latest",) in fake.calls

    window.intelligence_undo_latest.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert ("undo_latest",) in fake.calls
    window.close()
    app.processEvents()


def test_screenshot_intelligence_requires_consent_before_enable_and_launches_after_success(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    agent = tmp_path / "FroganizeScreenshotAgent.app"
    agent.mkdir()
    launched: list[Path] = []
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        environment={"FROGANIZE_SCREENSHOT_AGENT_APP": str(agent)},
        intelligence_paths=IntelligencePaths.from_root(tmp_path / "state"),
        intelligence_controller=fake,
        screenshot_launcher=launched.append,
    )
    window.show()
    window.refresh_intelligence_control()
    _wait_until(lambda: not window._intelligence_busy and window._intelligence_state is not None)

    window.intelligence_enabled.setChecked(True)
    app.processEvents()
    assert not window.intelligence_enabled.isChecked()
    assert ("set_enabled", True) not in fake.calls
    assert launched == []
    assert "同意" in window.intelligence_result.text()

    window.intelligence_consent.setChecked(True)
    window.intelligence_enabled.setChecked(True)
    _wait_until(lambda: not window._intelligence_busy)
    assert ("set_enabled", True) in fake.calls
    assert launched == [agent.resolve()]
    assert window.intelligence_enabled.isChecked()
    assert not window.intelligence_consent.isEnabled()

    # The UI prevents consent from silently diverging while processing stays on.
    window.intelligence_consent.setChecked(False)
    app.processEvents()
    assert window.intelligence_consent.isChecked()
    assert fake.state.enabled is True

    window.intelligence_enabled.setChecked(False)
    _wait_until(lambda: not window._intelligence_busy)
    assert ("set_enabled", False) in fake.calls
    assert not fake.state.enabled
    assert not window.intelligence_enabled.isChecked()
    assert not window.intelligence_consent.isChecked()
    assert launched == [agent.resolve()]
    window.close()
    app.processEvents()


def test_screenshot_intelligence_accepts_user_supplied_api_configuration(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
    )
    window.show()
    window.intelligence_nav.click()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
    )

    endpoint = "https://inference.example/v1/chat/completions"
    window.intelligence_custom_endpoint.setText(endpoint)
    window.intelligence_custom_model.setText("vision-model")
    window.intelligence_save_custom.click()
    _wait_until(lambda: not window._intelligence_busy)

    assert (
        "configure_custom_provider",
        endpoint,
        "vision-model",
    ) in fake.calls
    assert fake.state.custom_endpoint == endpoint
    assert fake.state.custom_model == "vision-model"
    window.close()
    app.processEvents()


def test_enabled_screenshot_state_starts_background_agent_only_once(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    fake.state = replace(fake.state, enabled=True, upload_consent=True)
    agent = tmp_path / "FroganizeScreenshotAgent.app"
    agent.mkdir()
    launched: list[Path] = []
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        environment={"FROGANIZE_SCREENSHOT_AGENT_APP": str(agent)},
        intelligence_paths=IntelligencePaths.from_root(tmp_path / "state"),
        intelligence_controller=fake,
        screenshot_launcher=launched.append,
    )
    window.show()

    # Opening the page schedules get_state. An authoritative enabled state
    # must activate the background processor without requiring the advanced
    # button, but repeated refreshes must not issue repeated open requests.
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
        and ("get_state",) in fake.calls
    )
    assert launched == [agent.resolve()]
    assert "后台处理组件" in window.open_intelligence_button.text()
    assert "菜单栏" not in window.intelligence_launch_message.text()

    get_state_count = fake.calls.count(("get_state",))
    window.refresh_intelligence_control()
    _wait_until(
        lambda: not window._intelligence_busy
        and fake.calls.count(("get_state",)) > get_state_count
    )
    assert launched == [agent.resolve()]

    window.close()
    app.processEvents()


def test_enabled_screenshot_state_reports_agent_start_failure_without_retry_loop(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    fake.state = replace(fake.state, enabled=True, upload_consent=True)
    agent = tmp_path / "FroganizeScreenshotAgent.app"
    agent.mkdir()
    attempts: list[Path] = []

    def fail_to_launch(path: Path) -> None:
        attempts.append(path)
        raise OSError("LaunchServices unavailable")

    window = FroganizeWindow(
        backend,
        auto_assess=False,
        environment={"FROGANIZE_SCREENSHOT_AGENT_APP": str(agent)},
        intelligence_paths=IntelligencePaths.from_root(tmp_path / "state"),
        intelligence_controller=fake,
        screenshot_launcher=fail_to_launch,
    )
    window.show()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
        and ("get_state",) in fake.calls
    )

    assert attempts == [agent.resolve()]
    assert "已启用" in window.intelligence_launch_message.text()
    assert "未能自动启动" in window.intelligence_launch_message.text()
    assert "LaunchServices unavailable" in window.intelligence_launch_message.text()

    get_state_count = fake.calls.count(("get_state",))
    window.refresh_intelligence_control()
    _wait_until(
        lambda: not window._intelligence_busy
        and fake.calls.count(("get_state",)) > get_state_count
    )
    assert attempts == [agent.resolve()]
    assert "未能自动启动" in window.intelligence_launch_message.text()

    window.close()
    app.processEvents()


def test_screenshot_intelligence_busy_is_independent_from_desktop_busy(
    tmp_path: Path,
) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
    )
    window.show()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
    )

    window._set_busy(True, "Desktop working")
    assert window._busy is True
    assert window._intelligence_busy is False
    assert window.intelligence_choose_folder.isEnabled()

    window._set_intelligence_busy(True, "Intelligence working")
    assert window._busy is True
    assert window._intelligence_busy is True
    assert not window.intelligence_choose_folder.isEnabled()
    assert not window.intelligence_refresh_button.isEnabled()
    assert not window.refresh_button.isEnabled()

    window._set_intelligence_busy(False, "")
    assert window._busy is True
    assert window.intelligence_choose_folder.isEnabled()
    assert window.intelligence_refresh_button.isEnabled()
    window._set_busy(False, "")
    window.close()
    app.processEvents()


def test_screenshot_api_key_is_not_undoable_even_when_save_fails(
    tmp_path: Path,
) -> None:
    class FailingKeyController(_FakeIntelligenceController):
        def save_api_key(self, provider: str, api_key: str) -> IntelligenceControlResult:
            self.calls.append(("save_api_key", provider))
            raise RuntimeError("safe key save failure")

    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = FailingKeyController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
    )
    window.show()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
    )

    window.intelligence_api_key.setText("cannot-restore-this-key")
    window.intelligence_save_key.click()
    _wait_until(lambda: not window._intelligence_busy)

    assert window.intelligence_api_key.text() == ""
    assert not window.intelligence_api_key.isUndoAvailable()
    window.intelligence_api_key.undo()
    assert window.intelligence_api_key.text() == ""
    assert "cannot-restore-this-key" not in window.intelligence_result.text()
    assert "safe key save failure" in window.intelligence_result.text()
    window.close()
    app.processEvents()


def test_remove_screenshot_key_requires_confirmation_and_updates_state(
    tmp_path: Path,
) -> None:
    decisions = iter((False, True))
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = _FakeIntelligenceController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
        confirm=lambda _title, _body: next(decisions),
    )
    window.show()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
    )

    window.intelligence_remove_key.click()
    app.processEvents()
    assert not any(call[0] == "remove_api_key" for call in fake.calls)
    assert window.intelligence_remove_key.isEnabled()

    window.intelligence_remove_key.click()
    _wait_until(lambda: not window._intelligence_busy)
    assert ("remove_api_key", "customOpenAICompatible") in fake.calls
    assert not fake.state.credential_configured
    assert window.intelligence_credential.text() == "API Key 尚未配置"
    assert not window.intelligence_remove_key.isEnabled()
    window.close()
    app.processEvents()


def test_failed_api_configuration_save_rolls_back_visible_values(
    tmp_path: Path,
) -> None:
    class FailingConfigurationController(_FakeIntelligenceController):
        def configure_custom_provider(
            self, endpoint: str, model: str
        ) -> IntelligenceControlResult:
            self.calls.append(("configure_custom_provider", endpoint, model))
            raise RuntimeError("safe API configuration failure")

    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = FailingConfigurationController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
    )
    window.show()
    _wait_until(
        lambda: not window._intelligence_busy
        and window._intelligence_state is not None
    )

    window.intelligence_custom_endpoint.setText(
        "https://changed.example/v1/chat/completions"
    )
    window.intelligence_custom_model.setText("changed-model")
    window.intelligence_save_custom.click()
    _wait_until(lambda: not window._intelligence_busy)

    assert (
        "configure_custom_provider",
        "https://changed.example/v1/chat/completions",
        "changed-model",
    ) in fake.calls
    assert fake.state.custom_model == "vision-model"
    assert window.intelligence_custom_model.text() == "vision-model"
    assert "safe API configuration failure" in window.intelligence_result.text()
    window.close()
    app.processEvents()


def test_screenshot_agent_symlink_override_is_not_opened(tmp_path: Path) -> None:
    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    real_agent = tmp_path / "RealScreenshotAgent.app"
    real_agent.mkdir()
    linked_agent = tmp_path / "LinkedScreenshotAgent.app"
    linked_agent.symlink_to(real_agent, target_is_directory=True)
    launched: list[Path] = []
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        environment={"FROGANIZE_SCREENSHOT_AGENT_APP": str(linked_agent)},
        screenshot_launcher=launched.append,
    )

    assert not window.open_intelligence_button.isEnabled()
    window.open_intelligence_button.click()
    app.processEvents()
    assert launched == []
    assert "未找到可安全打开" in window.intelligence_launch_message.text()
    window.close()
    app.processEvents()


def test_screenshot_intelligence_failed_enable_restores_authoritative_state(
    tmp_path: Path,
) -> None:
    class FailingController(_FakeIntelligenceController):
        def set_enabled(self, enabled: bool) -> IntelligenceControlResult:
            self.calls.append(("set_enabled", enabled))
            raise RuntimeError("safe test failure")

    app = _qt_app()
    backend, _workspace, _desktop = _setup(tmp_path)
    screenshots = tmp_path / "Screenshots"
    screenshots.mkdir()
    fake = FailingController(screenshots)
    window = FroganizeWindow(
        backend,
        auto_assess=False,
        intelligence_controller=fake,
    )
    window.show()
    window.refresh_intelligence_control()
    _wait_until(lambda: not window._intelligence_busy and window._intelligence_state is not None)

    window.intelligence_consent.setChecked(True)
    window.intelligence_enabled.setChecked(True)
    _wait_until(lambda: not window._intelligence_busy)

    assert ("set_enabled", True) in fake.calls
    assert not window.intelligence_enabled.isChecked()
    assert not window.intelligence_consent.isChecked()
    assert "safe test failure" in window.intelligence_result.text()
    window.close()
    app.processEvents()
