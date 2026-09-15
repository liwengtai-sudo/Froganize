"""Native Qt desktop interface for Froganize.

This module deliberately talks to the application service directly.  It does
not start an HTTP server, embed a browser, or use ``QWebEngine``.
"""

from __future__ import annotations

import calendar as calendar_module
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtSvg import QSvgRenderer

from dropnest.models import (
    BatchResult,
    DesktopAssessment,
    HistoryBatch,
    HistoryCalendar,
    OperationStatus,
    PlanStatus,
    StatusReport,
)
from dropnest.intelligence_history import IntelligencePaths
from dropnest.intelligence_status import get_intelligence_status
from dropnest.intelligence_control import (
    CUSTOM_PROVIDER_ID,
    IntelligenceControlResult,
    IntelligenceController,
    IntelligenceControlState,
    SubprocessIntelligenceController,
)


SCREENSHOT_AGENT_RELATIVE_PATH = Path(
    "Contents/Library/LoginItems/FroganizeScreenshotAgent.app"
)
SCREENSHOT_AGENT_OVERRIDE = "FROGANIZE_SCREENSHOT_AGENT_APP"
ScreenshotLauncher = Callable[[Path], object]
FolderPicker = Callable[[QWidget, str], Path | None]


def _default_screenshot_launcher(path: Path) -> None:
    """Ask LaunchServices to open the fixed Screenshot Intelligence app."""
    if sys.platform != "darwin":
        raise OSError("Screenshot Intelligence can currently be opened only on macOS.")
    subprocess.run(["/usr/bin/open", str(path)], check=True)


def _default_folder_picker(parent: QWidget, current: str) -> Path | None:
    selected = QFileDialog.getExistingDirectory(
        parent,
        "选择截图保存目录",
        current or str(Path.home()),
        QFileDialog.Option.ShowDirsOnly,
    )
    return None if not selected else Path(selected)


def screenshot_agent_path(environment: Mapping[str, str]) -> Path | None:
    """Resolve the packaged agent, or an explicit development-only override."""
    if getattr(sys, "frozen", False):
        bundle = Path(sys.executable).resolve(strict=False).parents[2]
        return bundle / SCREENSHOT_AGENT_RELATIVE_PATH
    override = environment.get(SCREENSHOT_AGENT_OVERRIDE)
    if not override:
        return None
    candidate = Path(override).expanduser()
    if not candidate.is_absolute():
        return None
    # Preserve the final path component so the availability check can reject
    # an explicit development override that is itself a symlink.
    return Path(os.path.abspath(candidate))


def _intelligence_paths(environment: Mapping[str, str]) -> IntelligencePaths | None:
    root = environment.get("FROGANIZE_STATE_DIR") or environment.get(
        "FROGANIZE_APP_SUPPORT_ROOT"
    )
    return None if not root else IntelligencePaths.from_root(Path(root))


class AssessmentSession(Protocol):
    id: str
    assessment: DesktopAssessment


class DesktopBackend(Protocol):
    workspace: Path
    desktop: Path
    timeline: Path

    def assess(self) -> AssessmentSession: ...
    def status(self, *, scan_source: bool = False) -> StatusReport: ...
    def collect_all(self) -> BatchResult: ...
    def archive(self, assessment_id: str, names: tuple[str, ...]) -> BatchResult: ...
    def trash(self, assessment_id: str, names: tuple[str, ...]) -> BatchResult: ...
    def undo(self, *, expected_batch_id: str | None = None) -> BatchResult: ...
    def history_calendar(self) -> HistoryCalendar: ...
    def clear_assessment(self) -> None: ...
    def open_folder(self, target: str) -> Any: ...
    def reveal_item(self, assessment_id: str, name: str) -> Any: ...


class _WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class _Worker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:  # translated into a concise UI error
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


def _mascot() -> QPixmap:
    pixmap = QPixmap()
    try:
        data = resources.files("dropnest").joinpath(
            "web_assets", "froganize-mascot.png"
        ).read_bytes()
        pixmap.loadFromData(data)
    except (OSError, FileNotFoundError):
        pass
    return pixmap


def _vector_mascot(name: str, logical_size: int) -> QPixmap:
    """Render a packaged SVG at Retina density for crisp native UI use."""
    try:
        data = resources.files("dropnest").joinpath("web_assets", name).read_bytes()
    except (OSError, FileNotFoundError):
        return QPixmap()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return QPixmap()
    density = 2
    pixmap = QPixmap(logical_size * density, logical_size * density)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(density)
    return pixmap


class _CalendarDayButton(QPushButton):
    """A lightweight glass calendar cell with a tiny mascot selection mark."""

    def __init__(self, mascot: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("calendarDay")
        self._mascot_mark = mascot

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -3.0)
        selected = self.isChecked()
        has_history = bool(self.property("hasHistory"))
        is_today = bool(self.property("today"))
        hovered = self.underMouse() and self.isEnabled()

        shadow = QRectF(cell).translated(0.0, 2.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(34, 58, 91, 15 if not hovered else 23))
        painter.drawRoundedRect(shadow, 13.0, 13.0)

        glass = QLinearGradient(cell.topLeft(), cell.bottomRight())
        if selected:
            glass.setColorAt(0.0, QColor(255, 255, 255, 235))
            glass.setColorAt(0.48, QColor(238, 246, 255, 190))
            glass.setColorAt(1.0, QColor(197, 220, 249, 112))
            border = QColor(63, 111, 180, 150)
        elif has_history:
            glass.setColorAt(0.0, QColor(255, 255, 255, 230))
            glass.setColorAt(0.52, QColor(255, 249, 219, 175))
            glass.setColorAt(1.0, QColor(248, 207, 76, 78))
            border = QColor(255, 255, 255, 225)
        else:
            glass.setColorAt(0.0, QColor(255, 255, 255, 205))
            glass.setColorAt(1.0, QColor(255, 255, 255, 105))
            border = QColor(255, 255, 255, 190)
        if hovered and not selected:
            glass.setColorAt(0.0, QColor(255, 255, 255, 245))

        painter.setBrush(glass)
        painter.setPen(QPen(border, 1.15))
        painter.drawRoundedRect(cell, 13.0, 13.0)
        if is_today and not selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(69, 112, 177, 112), 1.2))
            painter.drawRoundedRect(cell.adjusted(1.0, 1.0, -1.0, -1.0), 12.0, 12.0)

        day_number = self.property("dayNumber")
        item_count = self.property("itemCount")
        if not isinstance(day_number, int):
            return
        if not isinstance(item_count, int):
            item_count = 0

        font = painter.font()
        font.setBold(has_history or selected)
        font.setPointSizeF(11.5)
        painter.setFont(font)
        painter.setPen(QColor("#19365f") if has_history or selected else QColor("#536177"))
        if item_count:
            painter.drawText(
                QRectF(cell.left(), cell.top() + 3.0, cell.width(), 20.0),
                Qt.AlignCenter,
                str(day_number),
            )
            small_font = painter.font()
            small_font.setPointSizeF(8.0)
            small_font.setBold(True)
            painter.setFont(small_font)
            count_width = cell.width() - (20.0 if selected else 0.0)
            painter.drawText(
                QRectF(cell.left() + 3.0, cell.top() + 25.0, count_width - 4.0, 15.0),
                Qt.AlignCenter,
                f"{item_count} 项",
            )
        else:
            painter.drawText(cell, Qt.AlignCenter, str(day_number))

        if selected and not self._mascot_mark.isNull():
            painter.setOpacity(0.96)
            target = QRectF(cell.right() - 22.0, cell.bottom() - 21.0, 19.0, 19.0)
            painter.drawPixmap(
                target,
                self._mascot_mark,
                QRectF(self._mascot_mark.rect()),
            )


class _GlassBackdrop(QWidget):
    """Paint the soft light field visible through translucent UI surfaces."""

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base.setColorAt(0.0, QColor("#eef4fb"))
        base.setColorAt(0.48, QColor("#faf8f2"))
        base.setColorAt(1.0, QColor("#edf3f9"))
        painter.fillRect(rect, base)

        # Restrained brand-colour light pools create depth behind the glass.
        lights = (
            (0.13, 0.16, 0.48, QColor(247, 216, 106, 92)),
            (0.88, 0.10, 0.42, QColor(94, 145, 224, 68)),
            (0.70, 0.91, 0.50, QColor(255, 255, 255, 150)),
        )
        longest = max(rect.width(), rect.height())
        for x, y, size, colour in lights:
            glow = QRadialGradient(
                QPointF(rect.width() * x, rect.height() * y),
                longest * size,
            )
            glow.setColorAt(0.0, colour)
            edge = QColor(colour)
            edge.setAlpha(0)
            glow.setColorAt(1.0, edge)
            painter.fillRect(rect, glow)

        painter.end()


def _add_glass_shadow(
    widget: QWidget,
    *,
    blur: int = 34,
    y_offset: int = 10,
    alpha: int = 38,
) -> None:
    """Give a translucent surface subtle elevation without changing layout."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(25, 48, 82, alpha))
    widget.setGraphicsEffect(shadow)


class FroganizeWindow(QMainWindow):
    """One native window containing the complete first-run workflow."""

    def __init__(
        self,
        backend: DesktopBackend,
        *,
        auto_assess: bool = True,
        confirm: Callable[[str, str], bool] | None = None,
        environment: Mapping[str, str] | None = None,
        intelligence_paths: IntelligencePaths | None = None,
        screenshot_launcher: ScreenshotLauncher = _default_screenshot_launcher,
        intelligence_controller: IntelligenceController | None = None,
        folder_picker: FolderPicker = _default_folder_picker,
    ) -> None:
        super().__init__()
        self.backend = backend
        self._confirm = confirm
        self._environment = os.environ if environment is None else environment
        self._intelligence_paths = (
            intelligence_paths
            if intelligence_paths is not None
            else _intelligence_paths(self._environment)
        )
        self._screenshot_launcher = screenshot_launcher
        self._screenshot_agent = screenshot_agent_path(self._environment)
        # LaunchServices may activate an already-running helper, but repeatedly
        # calling ``open`` for every state render is still noisy and can race
        # with application startup.  Track the request for this GUI process;
        # disabling resets it so a later explicit re-enable can start again.
        self._intelligence_agent_start_requested = False
        self._intelligence_agent_start_error: str | None = None
        self._intelligence_controller = (
            intelligence_controller
            if intelligence_controller is not None
            else SubprocessIntelligenceController.from_environment(self._environment)
        )
        self._folder_picker = folder_picker
        self._intelligence_state: IntelligenceControlState | None = None
        self._intelligence_busy = False
        self._intelligence_workers: set[_Worker] = set()
        self._updating_intelligence_form = False
        self._pool = QThreadPool(self)
        self._workers: set[_Worker] = set()
        self._session_id: str | None = None
        self._assessment: DesktopAssessment | None = None
        self._busy = False
        self._status_report: StatusReport | None = None
        self._refresh_pending = False
        self._history_calendar: HistoryCalendar | None = None
        self._history_month = date.today().replace(day=1)
        self._selected_history_day = date.today()
        self._history_reload_pending = False
        self._history_preserve_result = False

        self.setWindowTitle("Froganize")
        self.setMinimumSize(860, 620)
        self.resize(1000, 720)
        mascot = _mascot()
        if not mascot.isNull():
            self.setWindowIcon(QIcon(mascot))
        self._build_ui(mascot)
        self._apply_style()
        self.refresh_intelligence_status()
        if self._intelligence_controller is not None:
            QTimer.singleShot(0, self.refresh_intelligence_control)
        QShortcut(QKeySequence.StandardKey.Refresh, self).activated.connect(
            self.refresh_assessment
        )
        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self._undo)
        if auto_assess:
            QTimer.singleShot(0, self.refresh_assessment)

    def _build_ui(self, mascot: QPixmap) -> None:
        root = _GlassBackdrop(objectName="glassRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(214)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 24, 22, 20)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setFixedSize(50, 50)
        sidebar_mascot = _vector_mascot("froganize-idle.svg", 50)
        if not sidebar_mascot.isNull():
            mark.setPixmap(sidebar_mascot)
        brand.addWidget(mark)
        title = QLabel("Froganize", objectName="brand")
        brand.addWidget(title)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(30)

        self._navigation = QButtonGroup(self)
        self._navigation.setExclusive(True)
        self.desktop_nav = self._nav_button("收好桌面", 0)
        self.history_nav = self._nav_button("整理日历", 1)
        self.intelligence_nav = self._nav_button("截图智能", 2)
        for button in (
            self.desktop_nav,
            self.history_nav,
            self.intelligence_nav,
        ):
            side.addWidget(button)
        self.desktop_nav.setChecked(True)
        side.addStretch()
        privacy = QLabel(
            "整理魔法只在本机\n隐藏项和系统项会留在原位",
            objectName="privacy",
        )
        side.addWidget(privacy)
        root_layout.addWidget(sidebar)

        self.pages = QStackedWidget(objectName="pages")
        self.pages.addWidget(self._desktop_page())
        self.pages.addWidget(self._history_page())
        self.pages.addWidget(self._intelligence_page())
        self.desktop_nav.clicked.connect(self.refresh_assessment)
        self.history_nav.clicked.connect(self.refresh_history)
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _intelligence_page(self) -> QWidget:
        page = QWidget(objectName="intelligencePage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(38, 30, 38, 26)
        outer.setSpacing(12)
        outer.addWidget(QLabel("截图智能", objectName="pageTitle"))
        subtitle = QLabel(
            "在一个面板里完成目录、AI 接口、凭证、启停、立即处理和撤销。",
            objectName="subtitle",
        )
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 6, 4)
        layout.setSpacing(12)

        self.intelligence_result = QLabel(objectName="resultBanner")
        self.intelligence_result.setWordWrap(True)
        self.intelligence_result.hide()
        layout.addWidget(self.intelligence_result)

        setup_card = QFrame(objectName="groupCard")
        _add_glass_shadow(setup_card, blur=26, y_offset=7, alpha=26)
        setup = QVBoxLayout(setup_card)
        setup.setSpacing(10)
        setup.addWidget(QLabel("基本设置", objectName="groupTitle"))
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("截图目录"))
        self.intelligence_folder = QLineEdit()
        self.intelligence_folder.setReadOnly(True)
        self.intelligence_folder.setPlaceholderText("尚未选择")
        self.intelligence_folder.setObjectName("intelligenceFolder")
        self.intelligence_choose_folder = QPushButton("选择…")
        self.intelligence_choose_folder.clicked.connect(self._choose_intelligence_folder)
        folder_row.addWidget(self.intelligence_folder, 1)
        folder_row.addWidget(self.intelligence_choose_folder)
        setup.addLayout(folder_row)

        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(QLabel("API 地址"))
        self.intelligence_custom_endpoint = QLineEdit()
        self.intelligence_custom_endpoint.setPlaceholderText(
            "https://example.com/v1/chat/completions"
        )
        endpoint_row.addWidget(self.intelligence_custom_endpoint, 1)
        setup.addLayout(endpoint_row)
        custom_model_row = QHBoxLayout()
        custom_model_row.addWidget(QLabel("模型名称"))
        self.intelligence_custom_model = QLineEdit()
        self.intelligence_custom_model.setPlaceholderText("填写接口支持的模型名称")
        custom_model_row.addWidget(self.intelligence_custom_model, 1)
        self.intelligence_save_custom = QPushButton("保存 API 配置")
        self.intelligence_save_custom.clicked.connect(
            self._save_custom_intelligence_provider
        )
        custom_model_row.addWidget(self.intelligence_save_custom)
        setup.addLayout(custom_model_row)
        custom_note = QLabel(
            "填写支持 OpenAI Chat Completions 格式的 HTTPS 接口；API Key 只保存在 macOS 钥匙串。",
            objectName="groupHint",
        )
        custom_note.setWordWrap(True)
        setup.addWidget(custom_note)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key"))
        self.intelligence_api_key = QLineEdit()
        self.intelligence_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.intelligence_api_key.setPlaceholderText("只发给 macOS 内嵌组件，保存后立即清空")
        self.intelligence_save_key = QPushButton("保存到 Keychain")
        self.intelligence_remove_key = QPushButton("移除")
        self.intelligence_test_connection = QPushButton("测试连接")
        self.intelligence_save_key.clicked.connect(self._save_intelligence_key)
        self.intelligence_remove_key.clicked.connect(self._remove_intelligence_key)
        self.intelligence_test_connection.clicked.connect(self._test_intelligence_connection)
        key_row.addWidget(self.intelligence_api_key, 1)
        key_row.addWidget(self.intelligence_save_key)
        key_row.addWidget(self.intelligence_remove_key)
        key_row.addWidget(self.intelligence_test_connection)
        setup.addLayout(key_row)
        self.intelligence_credential = QLabel(objectName="itemDetail")
        setup.addWidget(self.intelligence_credential)

        self.intelligence_consent = QCheckBox(
            "我同意将待处理截图发送到自己配置的 AI 接口进行语义分析"
        )
        self.intelligence_consent.stateChanged.connect(
            self._intelligence_consent_changed
        )
        self.intelligence_enabled = QCheckBox("允许上传并启用截图智能命名")
        self.intelligence_enabled.stateChanged.connect(self._toggle_intelligence)
        setup.addWidget(self.intelligence_consent)
        setup.addWidget(self.intelligence_enabled)
        layout.addWidget(setup_card)

        operation_card = QFrame(objectName="groupCard")
        _add_glass_shadow(operation_card, blur=26, y_offset=7, alpha=26)
        operation = QVBoxLayout(operation_card)
        operation.addWidget(QLabel("立即操作", objectName="groupTitle"))
        operation.addWidget(
            QLabel(
                "仅处理已授权目录中最新且可安全识别的系统截图。改名会写入本地历史。",
                objectName="itemDetail",
            )
        )
        immediate = QHBoxLayout()
        self.intelligence_process_latest = QPushButton("立即处理最新截图", objectName="primaryButton")
        self.intelligence_undo_latest = QPushButton("撤销最近截图改名")
        self.intelligence_process_latest.clicked.connect(self._process_latest_screenshot)
        self.intelligence_undo_latest.clicked.connect(self._undo_latest_screenshot)
        immediate.addWidget(self.intelligence_process_latest)
        immediate.addWidget(self.intelligence_undo_latest)
        immediate.addStretch()
        operation.addLayout(immediate)
        layout.addWidget(operation_card)

        card = QFrame(objectName="groupCard")
        _add_glass_shadow(card, blur=26, y_offset=7, alpha=26)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(9)
        self.intelligence_configuration = QLabel(objectName="groupTitle")
        self.intelligence_configuration.setWordWrap(True)
        self.intelligence_activity = QLabel(objectName="itemDetail")
        self.intelligence_activity.setWordWrap(True)
        self.intelligence_undo = QLabel(objectName="summary")
        self.intelligence_problem = QLabel(objectName="intelligenceProblem")
        self.intelligence_problem.setWordWrap(True)
        self.intelligence_runtime_note = QLabel(objectName="emptyText")
        self.intelligence_recent_activity = QLabel(objectName="itemDetail")
        self.intelligence_recent_activity.setWordWrap(True)
        for widget in (
            self.intelligence_configuration,
            self.intelligence_activity,
            self.intelligence_undo,
            self.intelligence_problem,
            self.intelligence_runtime_note,
            self.intelligence_recent_activity,
        ):
            card_layout.addWidget(widget)
        layout.addWidget(card)

        controls = QHBoxLayout()
        self.open_intelligence_button = QPushButton(
            "高级：打开后台处理组件"
        )
        self.open_intelligence_button.clicked.connect(
            self._open_screenshot_intelligence
        )
        self.intelligence_refresh_button = QPushButton("刷新全部状态")
        self.intelligence_refresh_button.clicked.connect(
            self.refresh_intelligence_control
        )
        controls.addWidget(self.open_intelligence_button)
        controls.addWidget(self.intelligence_refresh_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.intelligence_launch_message = QLabel(objectName="subtitle")
        self.intelligence_launch_message.setWordWrap(True)
        layout.addWidget(self.intelligence_launch_message)
        layout.addStretch()
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        return page

    def _nav_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text, objectName="navButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, page=index: self.pages.setCurrentIndex(page))
        self._navigation.addButton(button)
        return button

    def _desktop_page(self) -> QWidget:
        page = QWidget(objectName="desktopPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(46, 36, 46, 32)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(QLabel("给桌面一点整理魔法", objectName="pageTitle"))
        header.addStretch()
        self.refresh_button = QPushButton("重新看看")
        self.refresh_button.clicked.connect(self.refresh_assessment)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        magic_card = QFrame(objectName="magicCard")
        _add_glass_shadow(magic_card)
        magic = QVBoxLayout(magic_card)
        magic.setContentsMargins(34, 24, 34, 26)
        magic.setSpacing(10)
        self.hero_mascot = QLabel(objectName="heroMascot")
        self.hero_mascot.setAlignment(Qt.AlignCenter)
        self.hero_mascot.setMinimumHeight(210)
        self._set_hero_illustration("froganize-organizing.svg")
        magic.addWidget(self.hero_mascot)
        self.summary = QLabel("正在看看桌面…", objectName="magicTitle")
        self.summary.setAlignment(Qt.AlignCenter)
        magic.addWidget(self.summary)
        self.desktop_subtitle = QLabel(
            "蛙仔会把桌面第一层的文件和文件夹，按最后修改年月收进 Timeline。",
            objectName="magicSubtitle",
        )
        self.desktop_subtitle.setAlignment(Qt.AlignCenter)
        self.desktop_subtitle.setWordWrap(True)
        magic.addWidget(self.desktop_subtitle)
        self.collect_button = QPushButton("收好桌面", objectName="magicButton")
        self.collect_button.setMinimumHeight(54)
        self.collect_button.clicked.connect(self._collect_all)
        magic.addWidget(self.collect_button, alignment=Qt.AlignCenter)
        self.collection_note = QLabel(
            "不覆盖 · 文件夹不拆散 · 可以撤销",
            objectName="magicNote",
        )
        self.collection_note.setAlignment(Qt.AlignCenter)
        self.collection_note.setWordWrap(True)
        magic.addWidget(self.collection_note)
        layout.addWidget(magic_card, 1)

        self.result_banner = QLabel(objectName="resultBanner")
        self.result_banner.setAlignment(Qt.AlignCenter)
        self.result_banner.setWordWrap(True)
        self.result_banner.hide()
        layout.addWidget(self.result_banner)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.addStretch()
        self.open_timeline_button = QPushButton("打开收纳箱")
        self.open_timeline_button.clicked.connect(lambda: self._open_folder("timeline"))
        self.undo_button = QPushButton("撤销上一次")
        self.undo_button.clicked.connect(self._undo)
        actions.addWidget(self.open_timeline_button)
        actions.addWidget(self.undo_button)
        actions.addStretch()
        layout.addLayout(actions)
        self._update_collect_button()
        self._update_undo_button()
        return page

    def _history_page(self) -> QWidget:
        page = QWidget(objectName="historyPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(34, 30, 34, 26)
        outer.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(QLabel("蛙仔的整理日历", objectName="pageTitle"))
        subtitle = QLabel(
            "哪天收好了什么，一眼就能找到。较早记录只查看，最近一次可以安全撤销。",
            objectName="subtitle",
        )
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.history_refresh_button = QPushButton("刷新记录")
        self.history_refresh_button.clicked.connect(self.refresh_history)
        header.addWidget(self.history_refresh_button)
        outer.addLayout(header)

        self.history_result = QLabel(objectName="resultBanner")
        self.history_result.setWordWrap(True)
        self.history_result.hide()
        outer.addWidget(self.history_result)

        body = QHBoxLayout()
        body.setSpacing(14)
        calendar_card = QFrame(objectName="calendarCard")
        calendar_card.setMinimumWidth(330)
        calendar_card.setMaximumWidth(390)
        _add_glass_shadow(calendar_card, blur=25, y_offset=7, alpha=25)
        calendar_layout = QVBoxLayout(calendar_card)
        calendar_layout.setContentsMargins(18, 17, 18, 18)
        calendar_layout.setSpacing(10)

        month_row = QHBoxLayout()
        self.history_previous_month = QPushButton("‹", objectName="monthButton")
        self.history_previous_month.setAccessibleName("上个月")
        self.history_previous_month.clicked.connect(
            lambda: self._change_history_month(-1)
        )
        self.history_month_label = QLabel(objectName="calendarMonth")
        self.history_month_label.setAlignment(Qt.AlignCenter)
        self.history_next_month = QPushButton("›", objectName="monthButton")
        self.history_next_month.setAccessibleName("下个月")
        self.history_next_month.clicked.connect(
            lambda: self._change_history_month(1)
        )
        month_row.addWidget(self.history_previous_month)
        month_row.addWidget(self.history_month_label, 1)
        month_row.addWidget(self.history_next_month)
        calendar_layout.addLayout(month_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(6)
        for column, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            label = QLabel(name, objectName="weekday")
            label.setAlignment(Qt.AlignCenter)
            grid.addWidget(label, 0, column)
        self.history_day_buttons: list[QPushButton] = []
        calendar_mascot = _vector_mascot("froganize-calendar.svg", 24)
        for index in range(42):
            button = _CalendarDayButton(calendar_mascot)
            button.setCheckable(True)
            button.setMinimumSize(42, 50)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, current=button: self._select_history_day(
                    current
                )
            )
            self.history_day_buttons.append(button)
            grid.addWidget(button, 1 + index // 7, index % 7)
        calendar_layout.addLayout(grid)
        legend = QLabel(
            "暖金玻璃里有整理记录 · 蛙仔停留在当前选择",
            objectName="groupHint",
        )
        legend.setWordWrap(True)
        legend.setAlignment(Qt.AlignCenter)
        calendar_layout.addWidget(legend)
        body.addWidget(calendar_card)

        detail_card = QFrame(objectName="calendarDetailCard")
        _add_glass_shadow(detail_card, blur=25, y_offset=7, alpha=25)
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 15, 16, 15)
        detail_layout.setSpacing(10)
        self.history_detail_scroll = QScrollArea()
        self.history_detail_scroll.setWidgetResizable(True)
        self.history_detail_scroll.setFrameShape(QFrame.NoFrame)
        detail_layout.addWidget(self.history_detail_scroll, 1)
        self.history_undo_button = QPushButton(
            "选择最近一次整理后可以撤销", objectName="primaryButton"
        )
        self.history_undo_button.clicked.connect(self._undo_from_history)
        self.history_undo_button.setEnabled(False)
        detail_layout.addWidget(self.history_undo_button)
        body.addWidget(detail_card, 1)
        outer.addLayout(body, 1)
        self._render_history_calendar()
        return page

    def refresh_history(self) -> None:
        """Load the validated read-only Desktop history projection."""
        if self._busy:
            return
        if not self._history_preserve_result:
            self.history_result.hide()
        self._start_task(
            self.backend.history_calendar,
            self._apply_history_calendar,
            "蛙仔正在翻整理记录…",
            failure=self._history_failed,
        )

    def _history_failed(self, text: str) -> None:
        self._history_preserve_result = False
        self.history_result.setProperty("error", True)
        self.history_result.style().unpolish(self.history_result)
        self.history_result.style().polish(self.history_result)
        self.history_result.setText(f"无法读取整理记录：{text}")
        self.history_result.show()

    def _apply_history_calendar(self, payload: object) -> None:
        if not isinstance(payload, HistoryCalendar):
            self._history_failed("返回了无效的历史数据。")
            return
        first_load = self._history_calendar is None
        self._history_calendar = payload
        if first_load and payload.batches:
            latest_day = payload.batches[0].occurred_at.date()
            self._history_month = latest_day.replace(day=1)
            self._selected_history_day = latest_day
        self._render_history_calendar()
        self._history_preserve_result = False

    def _change_history_month(self, delta: int) -> None:
        absolute = self._history_month.year * 12 + self._history_month.month - 1 + delta
        year, zero_based_month = divmod(absolute, 12)
        if not 1 <= year <= 9999:
            return
        self._history_month = date(year, zero_based_month + 1, 1)
        self._selected_history_day = self._history_month
        self._render_history_calendar()

    def _select_history_day(self, button: QPushButton) -> None:
        raw = button.property("calendarDate")
        if not isinstance(raw, str):
            return
        try:
            self._selected_history_day = date.fromisoformat(raw)
        except ValueError:
            return
        self._render_history_calendar()

    def _history_batches_for_day(self, selected: date) -> tuple[HistoryBatch, ...]:
        if self._history_calendar is None:
            return ()
        return tuple(
            batch
            for batch in self._history_calendar.batches
            if batch.occurred_at.date() == selected
        )

    def _render_history_calendar(self) -> None:
        if not hasattr(self, "history_day_buttons"):
            return
        self.history_month_label.setText(
            f"{self._history_month.year} 年 {self._history_month.month} 月"
        )
        batches_by_day: dict[date, tuple[HistoryBatch, ...]] = {}
        if self._history_calendar is not None:
            for batch in self._history_calendar.batches:
                day = batch.occurred_at.date()
                batches_by_day[day] = batches_by_day.get(day, ()) + (batch,)

        weeks = calendar_module.Calendar(firstweekday=0).monthdayscalendar(
            self._history_month.year,
            self._history_month.month,
        )
        days = [day for week in weeks for day in week]
        days.extend([0] * (42 - len(days)))
        today = date.today()
        for button, day_number in zip(self.history_day_buttons, days, strict=True):
            if day_number == 0:
                button.hide()
                button.setProperty("calendarDate", None)
                continue
            button.show()
            current = date(
                self._history_month.year,
                self._history_month.month,
                day_number,
            )
            day_batches = batches_by_day.get(current, ())
            item_count = sum(len(batch.items) for batch in day_batches)
            button.setText(
                f"{day_number}\n{item_count} 项" if item_count else str(day_number)
            )
            button.setToolTip(
                f"{len(day_batches)} 次整理，共 {item_count} 项"
                if day_batches
                else "没有整理记录"
            )
            button.setProperty("calendarDate", current.isoformat())
            button.setProperty("dayNumber", day_number)
            button.setProperty("itemCount", item_count)
            button.setProperty("hasHistory", bool(day_batches))
            button.setProperty("today", current == today)
            button.setChecked(current == self._selected_history_day)
            button.style().unpolish(button)
            button.style().polish(button)
        self._render_history_detail()

    def _render_history_detail(self) -> None:
        selected = self._selected_history_day
        batches = self._history_batches_for_day(selected)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 6, 2)
        layout.setSpacing(10)
        title = QLabel(
            f"{selected.year} 年 {selected.month} 月 {selected.day} 日",
            objectName="groupTitle",
        )
        layout.addWidget(title)

        self._selected_history_undo_batch: HistoryBatch | None = None
        if not batches:
            calendar_frog = QLabel()
            calendar_frog.setAlignment(Qt.AlignCenter)
            calendar_frog.setPixmap(
                _vector_mascot("froganize-calendar.svg", 108)
            )
            layout.addWidget(calendar_frog)
            empty = QLabel(
                "这一天蛙仔没有施展整理魔法。\n点击金色日期，可以看看当时收好了什么。",
                objectName="emptyText",
            )
            empty.setWordWrap(True)
            layout.addWidget(empty)
        for batch in batches:
            card = QFrame(objectName="historyBatchCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)
            time_text = batch.occurred_at.strftime("%H:%M")
            status = "可撤销" if batch.undoable else (
                "已撤销" if batch.restored_count == len(batch.items) else "历史记录"
            )
            heading = QLabel(
                f"{time_text} · 收好 {len(batch.items)} 项 · {status}",
                objectName="historyBatchTitle",
            )
            card_layout.addWidget(heading)
            for item in batch.items[:50]:
                if item.restored:
                    state = "已放回桌面"
                elif item.restore_failed:
                    state = "上次撤销未成功"
                else:
                    state = "已在 Timeline"
                try:
                    target = item.destination.relative_to(self.backend.timeline)
                except ValueError:
                    target = item.destination
                detail = QLabel(
                    f"{item.source.name}  →  Timeline/{target}\n{state}",
                    objectName="historyItem",
                )
                detail.setWordWrap(True)
                detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
                card_layout.addWidget(detail)
            if len(batch.items) > 50:
                card_layout.addWidget(
                    QLabel(
                        f"另外 {len(batch.items) - 50} 项已折叠显示。",
                        objectName="groupHint",
                    )
                )
            layout.addWidget(card)
            if batch.undoable:
                self._selected_history_undo_batch = batch
        layout.addStretch()
        self.history_detail_scroll.setWidget(host)

        undoable = self._selected_history_undo_batch
        self.history_undo_button.setEnabled(undoable is not None and not self._busy)
        self.history_undo_button.setText(
            f"撤销最近整理 · {undoable.outstanding_count} 项"
            if undoable is not None
            else "只有最近一次未撤销的整理可以撤销"
        )

    def _undo_from_history(self) -> None:
        batch = self._selected_history_undo_batch
        if self._busy or batch is None or not batch.undoable:
            return
        names = [item.source.name for item in batch.items if not item.restored]
        preview = "\n".join(f"• {name}" for name in names[:5])
        if len(names) > 5:
            preview += f"\n• 以及另外 {len(names) - 5} 项"
        if not self._ask(
            "撤销最近一次整理",
            f"蛙仔会把这次整理的 {len(names)} 项放回原来的桌面位置。\n\n{preview}\n\n"
            "如果原位置已有同名项目，该项目会留在 Timeline，不会覆盖。",
        ):
            return
        self._assessment = None
        self._session_id = None
        self._history_reload_pending = True
        self._start_task(
            lambda: self.backend.undo(expected_batch_id=batch.batch_id),
            self._history_undo_done,
            "蛙仔正在把东西放回桌面…",
        )

    def _history_undo_done(self, payload: object) -> None:
        if not isinstance(payload, BatchResult):
            self._history_failed("撤销返回了无效结果。")
            return
        restored = payload.count(OperationStatus.RESTORED)
        failed = payload.count(OperationStatus.FAILED)
        self.history_result.setProperty("error", failed > 0)
        self.history_result.style().unpolish(self.history_result)
        self.history_result.style().polish(self.history_result)
        text = f"蛙仔已把 {restored} 项放回桌面。"
        if failed:
            text += f" {failed} 项因冲突或文件变化留在 Timeline，没有覆盖任何内容。"
        self.history_result.setText(text)
        self.history_result.show()
        self._history_preserve_result = True

    def refresh_intelligence_status(self) -> None:
        """Refresh the read-only Screenshot Intelligence projection."""
        status = get_intelligence_status(self._intelligence_paths)
        if status.configured and status.screenshot_root is not None:
            self.intelligence_configuration.setText(
                f"已配置截图目录\n{status.screenshot_root}"
            )
        else:
            self.intelligence_configuration.setText("尚未配置截图目录")
        if status.latest_renamed_name and status.latest_success_time:
            self.intelligence_activity.setText(
                f"最近改名：{status.latest_renamed_name}\n"
                f"记录时间：{status.latest_success_time}"
            )
        else:
            self.intelligence_activity.setText("还没有成功改名记录")
        self.intelligence_undo.setText(
            f"当前可撤销：{status.outstanding_rename_count} 项"
        )
        self.intelligence_problem.setText(
            "" if status.problem is None else f"状态需要注意：{status.problem}"
        )
        self.intelligence_problem.setVisible(status.problem is not None)
        if status.recent_activity:
            lines = ["最近活动："]
            for item in status.recent_activity:
                action = "撤销" if item.event_type.endswith("_undo") else "改名"
                lines.append(
                    f"{action} · {item.timestamp} · {item.original_name} → {item.renamed_name}"
                )
            self.intelligence_recent_activity.setText("\n".join(lines))
        else:
            self.intelligence_recent_activity.setText("最近活动：暂无")
        agent = self._screenshot_agent
        available = (
            agent is not None
            and agent.is_dir()
            and not agent.is_symlink()
        )
        self.open_intelligence_button.setEnabled(available)
        if (
            self._intelligence_agent_start_error is not None
            and self._intelligence_state is not None
            and self._intelligence_state.enabled
        ):
            self.intelligence_launch_message.setText(
                self._intelligence_agent_start_error
            )
        elif agent is None:
            self.intelligence_launch_message.setText(
                "开发环境未指定截图智能应用；打包版会使用内嵌组件。"
            )
        elif not available:
            self.intelligence_launch_message.setText("未找到可安全打开的截图智能组件。")
        elif (
            self._intelligence_agent_start_requested
            and self._intelligence_state is not None
            and self._intelligence_state.enabled
        ):
            self.intelligence_launch_message.setText(
                "截图智能已启用，已向 macOS 发送后台处理组件启动请求。"
            )
        else:
            self.intelligence_launch_message.setText(
                "截图监听与自动处理由内嵌后台组件执行；"
                "启用后会自动启动，也可在这里手动打开。"
            )

        if self._intelligence_controller is None:
            self.intelligence_runtime_note.setText(
                "未找到安全的控制组件；上述信息不代表后台组件是否正在运行。"
            )
        self._update_intelligence_controls()

    def refresh_intelligence_control(self) -> None:
        """Fetch authoritative settings from the embedded component."""
        self.refresh_intelligence_status()
        controller = self._intelligence_controller
        if controller is None:
            self._show_intelligence_result("截图智能控制组件不可用。", True)
            return
        self._start_intelligence_task(
            controller.get_state,
            self._apply_intelligence_result,
            "正在读取截图智能设置…",
        )

    def _apply_intelligence_result(self, payload: object) -> None:
        if not isinstance(payload, IntelligenceControlResult):
            self._show_intelligence_result("内嵌组件返回了无效结果。", True)
            return
        self._apply_intelligence_state(payload.state)
        self._show_intelligence_result(payload.message or "截图智能状态已更新。")
        self._ensure_intelligence_agent_running()
        self.refresh_intelligence_status()

    def _apply_intelligence_state(self, state: IntelligenceControlState) -> None:
        self._intelligence_state = state
        self._updating_intelligence_form = True
        try:
            self.intelligence_folder.setText(state.folder_path)
            self.intelligence_custom_endpoint.setText(state.custom_endpoint)
            self.intelligence_custom_model.setText(state.custom_model)
            self.intelligence_consent.setChecked(state.upload_consent)
            self.intelligence_enabled.setChecked(state.enabled)
            if state.credential_configured:
                source = (
                    f" · {state.credential_source}"
                    if state.credential_source
                    else ""
                )
                self.intelligence_credential.setText(f"API Key 已配置{source}")
            else:
                self.intelligence_credential.setText("API Key 尚未配置")
            working = "正在处理" if state.is_working else ("已启用" if state.enabled else "已停用")
            detail = state.status_message.strip()
            self.intelligence_runtime_note.setText(
                f"运行状态：{working}" + (f" · {detail}" if detail else "")
            )
        finally:
            self._updating_intelligence_form = False
        self._update_intelligence_controls()

    def _selected_provider_model(self) -> tuple[str, str] | None:
        state = self._intelligence_state
        if state is None:
            return None
        model = state.custom_model or state.model
        if not model:
            return None
        return CUSTOM_PROVIDER_ID, model

    def _save_custom_intelligence_provider(self) -> None:
        controller = self._intelligence_controller
        if controller is None or self._intelligence_busy:
            return
        endpoint = self.intelligence_custom_endpoint.text()
        model = self.intelligence_custom_model.text()
        if not endpoint or not model:
            self._show_intelligence_result(
                "请填写 API 地址和模型名称。", True
            )
            return
        self._start_intelligence_task(
            lambda: controller.configure_custom_provider(endpoint, model),
            self._apply_intelligence_result,
            "正在保存 API 配置…",
        )

    def _choose_intelligence_folder(self) -> None:
        controller = self._intelligence_controller
        if controller is None:
            self._show_intelligence_result("截图智能控制组件不可用。", True)
            return
        selected = self._folder_picker(self, self.intelligence_folder.text())
        if selected is None:
            return
        self._start_intelligence_task(
            lambda: controller.configure_folder(selected),
            self._apply_intelligence_result,
            "正在授权截图目录…",
        )

    def _save_intelligence_key(self) -> None:
        controller = self._intelligence_controller
        selected = self._selected_provider_model()
        key = self.intelligence_api_key.text()
        # setText(), unlike clear(), also clears Qt's undo/redo history so the
        # submitted credential cannot be restored with Command-Z.
        self.intelligence_api_key.setText("")
        if controller is None or selected is None:
            self._show_intelligence_result("截图智能控制组件不可用。", True)
            return
        if not key:
            self._show_intelligence_result("请先输入 API Key。", True)
            return
        provider, _model = selected
        self._start_intelligence_task(
            lambda: controller.save_api_key(provider, key),
            self._apply_intelligence_result,
            "正在安全保存 API Key…",
        )

    def _remove_intelligence_key(self) -> None:
        controller = self._intelligence_controller
        selected = self._selected_provider_model()
        if controller is None or selected is None:
            return
        provider, _model = selected
        if not self._ask(
            "移除 API Key",
            "从 macOS Keychain 中移除这个 AI 接口的 API Key？\n"
            "移除后截图智能将无法发送 AI 请求，直到再次配置。",
        ):
            return
        self._start_intelligence_task(
            lambda: controller.remove_api_key(provider),
            self._apply_intelligence_result,
            "正在移除 API Key…",
        )

    def _test_intelligence_connection(self) -> None:
        controller = self._intelligence_controller
        selected = self._selected_provider_model()
        if controller is None or selected is None:
            return
        provider, model = selected
        self._start_intelligence_task(
            lambda: controller.test_connection(provider, model),
            self._apply_intelligence_result,
            "正在测试 AI 连接…",
        )

    def _toggle_intelligence(self, state_value: int) -> None:
        if self._updating_intelligence_form:
            return
        enabled = state_value == Qt.CheckState.Checked.value
        if enabled and not self.intelligence_consent.isChecked():
            self._updating_intelligence_form = True
            self.intelligence_enabled.setChecked(False)
            self._updating_intelligence_form = False
            self._show_intelligence_result("启用前请先明确同意截图上传说明。", True)
            return
        controller = self._intelligence_controller
        if controller is None:
            self._show_intelligence_result("截图智能控制组件不可用。", True)
            return

        self._start_intelligence_task(
            lambda: controller.set_enabled(enabled),
            self._apply_intelligence_result,
            "正在允许上传并启用截图智能…"
            if enabled
            else "正在停用并撤回上传同意…",
        )

    def _intelligence_consent_changed(self, state_value: int) -> None:
        """Never leave a visible consent opt-out while the agent stays enabled."""
        if self._updating_intelligence_form:
            return
        unchecked = state_value != Qt.CheckState.Checked.value
        state = self._intelligence_state
        if unchecked and state is not None and state.enabled:
            # Disabled widgets cannot normally be clicked, but restore the
            # authoritative value if code/accessibility automation changes it.
            self._updating_intelligence_form = True
            self.intelligence_consent.setChecked(True)
            self._updating_intelligence_form = False

    def _ensure_intelligence_agent_running(self) -> None:
        """Start the worker once when authoritative state says it is enabled."""
        state = self._intelligence_state
        if state is None or not state.enabled:
            self._intelligence_agent_start_requested = False
            self._intelligence_agent_start_error = None
            return
        if self._intelligence_agent_start_requested:
            return
        agent = self._screenshot_agent
        if agent is None or not agent.is_dir() or agent.is_symlink():
            self._intelligence_agent_start_error = (
                "截图智能已启用，但未找到可安全启动的后台处理组件。"
            )
            return
        self._intelligence_agent_start_requested = True
        try:
            self._screenshot_launcher(agent)
        except (OSError, RuntimeError, ValueError) as exc:
            # Enabling already succeeded.  Keep that truthful result visible;
            # the user can retry from the advanced control without causing an
            # automatic launch loop on every state refresh.
            detail = str(exc).strip()
            self._intelligence_agent_start_error = (
                "截图智能已启用，但后台处理组件未能自动启动。"
                + (f"原因：{detail}" if detail else "")
            )
        else:
            self._intelligence_agent_start_error = None

    def _process_latest_screenshot(self) -> None:
        controller = self._intelligence_controller
        if controller is not None:
            self._start_intelligence_task(
                controller.process_latest,
                self._apply_intelligence_result,
                "正在处理最新截图…",
            )

    def _undo_latest_screenshot(self) -> None:
        controller = self._intelligence_controller
        if controller is not None:
            self._start_intelligence_task(
                controller.undo_latest,
                self._apply_intelligence_result,
                "正在撤销最近截图改名…",
            )

    def _start_intelligence_task(
        self,
        operation: Callable[[], Any],
        success: Callable[[object], None],
        message: str,
    ) -> None:
        if self._intelligence_busy:
            return
        self._set_intelligence_busy(True, message)
        worker = _Worker(operation)
        self._intelligence_workers.add(worker)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(self._intelligence_task_failed)
        worker.signals.finished.connect(
            lambda current=worker: self._intelligence_task_finished(current)
        )
        self._pool.start(worker)

    def _intelligence_task_failed(self, text: str) -> None:
        # Signals already changed the visible controls optimistically. Restore
        # the last authoritative state when the subprocess fails closed.
        if self._intelligence_state is not None:
            self._apply_intelligence_state(self._intelligence_state)
        self._show_intelligence_result(f"未完成：{text}", True)

    def _intelligence_task_finished(self, worker: _Worker) -> None:
        self._intelligence_workers.discard(worker)
        self._set_intelligence_busy(False, "")

    def _set_intelligence_busy(self, busy: bool, message: str) -> None:
        self._intelligence_busy = busy
        if message:
            self.intelligence_runtime_note.setText(message)
        self._update_intelligence_controls()

    def _update_intelligence_controls(self) -> None:
        controller_available = self._intelligence_controller is not None
        state = self._intelligence_state
        self.intelligence_refresh_button.setEnabled(
            controller_available and not self._intelligence_busy
        )
        enabled = (
            controller_available
            and state is not None
            and not self._intelligence_busy
        )
        for widget in (
            self.intelligence_choose_folder,
            self.intelligence_custom_endpoint,
            self.intelligence_custom_model,
            self.intelligence_save_custom,
            self.intelligence_api_key,
            self.intelligence_save_key,
            self.intelligence_remove_key,
            self.intelligence_test_connection,
            self.intelligence_consent,
            self.intelligence_enabled,
            self.intelligence_process_latest,
            self.intelligence_undo_latest,
        ):
            widget.setEnabled(enabled)
        if state is not None and enabled:
            custom_ready = bool(state.custom_endpoint and state.custom_model)
            self.intelligence_consent.setEnabled(not state.enabled)
            self.intelligence_remove_key.setEnabled(state.credential_configured)
            self.intelligence_test_connection.setEnabled(
                state.credential_configured and custom_ready
            )
            self.intelligence_process_latest.setEnabled(
                state.enabled
                and state.credential_configured
                and custom_ready
                and bool(state.folder_path)
            )
            self.intelligence_undo_latest.setEnabled(
                state.last_rename_event_id is not None
                or get_intelligence_status(self._intelligence_paths).outstanding_rename_count > 0
            )

    def _show_intelligence_result(self, text: str, error: bool = False) -> None:
        self.intelligence_result.setProperty("error", error)
        self.intelligence_result.style().unpolish(self.intelligence_result)
        self.intelligence_result.style().polish(self.intelligence_result)
        self.intelligence_result.setText(text)
        self.intelligence_result.show()

    def _open_screenshot_intelligence(self) -> None:
        """Open only the packaged background worker or development override."""
        agent = self._screenshot_agent
        if agent is None or not agent.is_dir() or agent.is_symlink():
            self.intelligence_launch_message.setText(
                "未找到可安全打开的截图智能组件。"
            )
            return
        try:
            self._screenshot_launcher(agent)
        except (OSError, RuntimeError, ValueError) as exc:
            self._intelligence_agent_start_error = (
                f"后台处理组件启动请求失败：{exc}"
            )
            self.intelligence_launch_message.setText(
                self._intelligence_agent_start_error
            )
            return
        self._intelligence_agent_start_requested = True
        self._intelligence_agent_start_error = None
        self.intelligence_launch_message.setText("已向 macOS 发送打开请求。")

    def refresh_assessment(self) -> None:
        if self._busy:
            return
        self.backend.clear_assessment()
        self._session_id = None
        self._assessment = None
        self._start_task(
            lambda: (self.backend.assess(), self.backend.status(scan_source=False)),
            self._apply_dashboard,
            "蛙仔正在看看桌面…",
        )

    def _apply_dashboard(self, payload: object) -> None:
        session, report = payload  # type: ignore[misc]
        self._session_id = str(session.id)
        self._assessment = session.assessment
        self._status_report = report
        self._render_collection(session.assessment)
        self._render_status(report)

    def _render_collection(self, assessment: DesktopAssessment) -> None:
        movable = sum(
            entry.plan_entry.status is PlanStatus.PLANNED
            for entry in assessment.entries
        )
        left_in_place = len(assessment.entries) - movable
        if movable:
            self._set_hero_illustration("froganize-organizing.svg")
            self.summary.setText(f"桌面有 {movable} 项可以一次收好")
            self.desktop_subtitle.setText(
                "蛙仔已经拿好文件夹魔法杖。点一下，它们会按最后修改年月完整收好。"
            )
        else:
            self._set_hero_illustration("froganize-success.svg")
            self.summary.setText("桌面已经很清爽了")
            self.desktop_subtitle.setText("蛙仔暂时不需要施展整理魔法。")
        self.collection_note.setText(
            "不覆盖 · 文件夹不拆散 · 可以撤销"
            + (
                f" · {left_in_place} 项因安全规则留在原位"
                if left_in_place
                else ""
            )
        )
        self._update_collect_button()

    def _set_hero_illustration(self, asset_name: str) -> None:
        if not hasattr(self, "hero_mascot"):
            return
        illustration = _vector_mascot(asset_name, 210)
        if not illustration.isNull():
            self.hero_mascot.setPixmap(illustration)

    def _render_status(self, report: StatusReport) -> None:
        self._update_undo_button()
        if report.problems:
            self._show_result("安全提示：" + "；".join(report.problems), True)

    def _ask(self, title: str, body: str) -> bool:
        if self._confirm is not None:
            return self._confirm(title, body)
        result = QMessageBox.question(
            self,
            title,
            body,
            QMessageBox.Cancel | QMessageBox.Ok,
            QMessageBox.Cancel,
        )
        # PySide6's native macOS dialog returns the selected StandardButton as
        # a plain int on some builds.  Identity comparison therefore treats a
        # real click on OK as Cancel even though both values are 1024.
        return result == QMessageBox.Ok

    def _collect_all(self) -> None:
        if self._busy or self._assessment is None:
            return
        movable = sum(
            entry.plan_entry.status is PlanStatus.PLANNED
            for entry in self._assessment.entries
        )
        if not movable:
            return
        self._start_task(
            self.backend.collect_all,
            self._collection_done,
            "蛙仔正在施展整理魔法…",
            refresh_after=True,
        )

    def _undo(self) -> None:
        if self._busy:
            return
        self._start_task(
            self.backend.undo,
            self._undo_done,
            "蛙仔正在把东西放回桌面…",
            refresh_after=True,
        )

    def _collection_done(self, result: object) -> None:
        batch = result
        assert isinstance(batch, BatchResult)
        self._session_id = None
        self._assessment = None
        moved = batch.count(OperationStatus.MOVED)
        skipped = batch.count(OperationStatus.SKIPPED)
        failed = batch.count(OperationStatus.FAILED)
        if moved:
            self._set_hero_illustration("froganize-success.svg")
        message = f"整理魔法完成，蛙仔已收好 {moved} 项。"
        if skipped:
            message += f" {skipped} 项因安全规则留在原位。"
        failures = [item for item in batch.results if item.status is OperationStatus.FAILED]
        if failures and failures[0].reason:
            message += f"\n未能收好 {failed} 项：{failures[0].reason}"
        self._show_result(message, failed > 0)

    def _undo_done(self, result: object) -> None:
        batch = result
        assert isinstance(batch, BatchResult)
        restored = batch.count(OperationStatus.RESTORED)
        failed = batch.count(OperationStatus.FAILED)
        if restored:
            self._set_hero_illustration("froganize-idle.svg")
        if restored:
            message = f"蛙仔已把 {restored} 项放回桌面。"
        elif failed:
            message = "有可撤销的项目，但这次没有成功放回桌面。"
        else:
            message = "没有可以撤销的上一次整理。"
        failures = [item for item in batch.results if item.status is OperationStatus.FAILED]
        if failures and failures[0].reason:
            message += f"\n有 {failed} 项未能恢复：{failures[0].reason}"
        self._show_result(message, failed > 0)

    def _open_folder(self, target: str) -> None:
        self._start_task(
            lambda: self.backend.open_folder(target),
            lambda _result: self._restore_collection_copy(),
            "正在打开 Finder…",
        )

    def _reveal(self, name: str) -> None:
        if self._session_id:
            session_id = self._session_id
            self._start_task(
                lambda: self.backend.reveal_item(session_id, name),
                lambda _result: self._restore_collection_copy(),
                "正在 Finder 中显示…",
            )

    def _restore_collection_copy(self) -> None:
        if self._assessment is not None:
            self._render_collection(self._assessment)

    def _show_result(self, text: str, error: bool = False) -> None:
        self.result_banner.setProperty("error", error)
        self.result_banner.style().unpolish(self.result_banner)
        self.result_banner.style().polish(self.result_banner)
        self.result_banner.setText(text)
        self.result_banner.show()

    def _start_task(
        self,
        operation: Callable[[], Any],
        success: Callable[[object], None],
        message: str,
        *,
        refresh_after: bool = False,
        failure: Callable[[str], None] | None = None,
    ) -> None:
        if self._busy:
            return
        self._set_busy(True, message)
        self._refresh_pending = refresh_after
        worker = _Worker(operation)
        self._workers.add(worker)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(
            failure
            if failure is not None
            else lambda text: self._show_result(f"未完成：{text}", True)
        )
        worker.signals.finished.connect(lambda current=worker: self._task_finished(current))
        self._pool.start(worker)

    def _task_finished(self, worker: _Worker) -> None:
        self._workers.discard(worker)
        self._set_busy(False, "")
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh_assessment)
        if self._history_reload_pending:
            self._history_reload_pending = False
            QTimer.singleShot(0, self.refresh_history)

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        if message:
            self.desktop_subtitle.setText(message)
        for button in (
            self.refresh_button,
            self.open_timeline_button,
        ):
            button.setEnabled(not busy)
        for name in (
            "history_refresh_button",
            "history_previous_month",
            "history_next_month",
        ):
            button = getattr(self, name, None)
            if isinstance(button, QPushButton):
                button.setEnabled(not busy)
        self._update_collect_button()
        self._update_undo_button()
        if hasattr(self, "history_detail_scroll"):
            self._render_history_detail()

    def _update_collect_button(self) -> None:
        assessment = self._assessment
        movable = 0 if assessment is None else sum(
            entry.plan_entry.status is PlanStatus.PLANNED
            for entry in assessment.entries
        )
        self.collect_button.setEnabled(not self._busy and movable > 0)
        self.collect_button.setText(
            f"收好桌面 · {movable} 项" if movable else "收好桌面"
        )

    def _update_undo_button(self) -> None:
        report = self._status_report
        self.undo_button.setEnabled(
            not self._busy
            and report is not None
            and report.history_valid
            and report.latest_moved_count > 0
            and report.latest_undo_status != "complete"
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            * {
                color: #17243d;
                font-family: "SF Pro Text", "PingFang SC", sans-serif;
            }
            QMainWindow { background: #edf3f9; }
            QWidget#glassRoot, QWidget#desktopPage, QWidget#historyPage,
            QWidget#intelligencePage,
            QStackedWidget#pages, QScrollArea, QScrollArea > QWidget,
            QScrollArea > QWidget > QWidget { background: transparent; }
            QFrame#sidebar {
                background: rgba(248, 250, 253, 184);
                border: 0;
                border-right: 1px solid rgba(255, 255, 255, 224);
            }
            QLabel#brand { font-size: 22px; font-weight: 800; color: #173b79; }
            QLabel#privacy { color: #68748a; font-size: 12px; line-height: 1.5; }
            QPushButton {
                border: 1px solid rgba(255, 255, 255, 220);
                border-radius: 11px;
                background: rgba(255, 255, 255, 172);
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #123e81;
                background: rgba(255, 255, 255, 225);
                border-color: rgba(76, 118, 180, 145);
            }
            QPushButton:pressed { background: rgba(229, 237, 248, 220); }
            QPushButton:focus { border-color: rgba(38, 84, 153, 185); }
            QPushButton:disabled {
                color: #9199a5;
                background: rgba(225, 229, 234, 135);
                border-color: rgba(255, 255, 255, 150);
            }
            QPushButton#navButton {
                text-align: left;
                border: 1px solid transparent;
                background: transparent;
                padding: 12px 14px;
                font-size: 14px;
            }
            QPushButton#navButton:hover { background: rgba(255, 255, 255, 118); }
            QPushButton#navButton:checked {
                color: #173f82;
                background: rgba(255, 248, 218, 188);
                border-color: rgba(255, 255, 255, 210);
            }
            QLabel#pageTitle { font-size: 28px; font-weight: 800; color: #152746; }
            QLabel#subtitle, QLabel#itemDetail, QLabel#emptyText { color: #657187; }
            QFrame#magicCard {
                background: rgba(255, 255, 255, 158);
                border: 1px solid rgba(255, 255, 255, 225);
                border-radius: 24px;
            }
            QLabel#magicTitle { font-size: 25px; font-weight: 800; color: #173b79; }
            QLabel#magicSubtitle { color: #626f84; font-size: 14px; }
            QLabel#magicNote { color: #758095; font-size: 12px; }
            QPushButton#magicButton {
                min-width: 250px;
                color: #153454;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffe789, stop:0.48 #f8d765, stop:1 #efc64e);
                border: 1px solid rgba(255, 255, 255, 225);
                border-radius: 17px;
                padding: 13px 28px;
                font-size: 18px;
                font-weight: 800;
            }
            QPushButton#magicButton:hover {
                color: #102f56;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffedaa, stop:0.5 #fbe17c, stop:1 #f2cd58);
                border-color: rgba(41, 84, 157, 150);
            }
            QPushButton#magicButton:pressed { background: #efc952; }
            QPushButton#magicButton:disabled {
                color: #8e95a0;
                background: rgba(221, 224, 227, 155);
                border-color: rgba(255, 255, 255, 150);
            }
            QLineEdit {
                background: rgba(255, 255, 255, 164);
                border: 1px solid rgba(255, 255, 255, 220);
                border-radius: 9px;
                padding: 8px 10px;
                selection-background-color: #315fa8;
            }
            QLineEdit:focus {
                background: rgba(255, 255, 255, 220);
                border-color: rgba(49, 95, 168, 165);
            }
            QLabel#intelligenceProblem {
                color: #8b3026;
                background: rgba(250, 233, 228, 190);
                border: 1px solid rgba(255, 255, 255, 190);
                border-radius: 8px;
                padding: 8px;
            }
            QLabel#summary { color: #294f94; font-weight: 700; }
            QLabel#resultBanner {
                background: rgba(225, 243, 222, 185);
                border: 1px solid rgba(255, 255, 255, 215);
                border-radius: 11px;
                padding: 10px 12px;
            }
            QLabel#resultBanner[error="true"] {
                background: rgba(250, 229, 225, 195);
                border-color: rgba(255, 255, 255, 210);
                color: #8b3026;
            }
            QFrame#groupCard, QLabel#largeCard {
                background: rgba(255, 255, 255, 154);
                border: 1px solid rgba(255, 255, 255, 220);
                border-radius: 16px;
                padding: 12px;
            }
            QFrame#itemRow {
                background: rgba(255, 255, 255, 106);
                border: 1px solid rgba(255, 255, 255, 138);
                border-radius: 10px;
            }
            QLabel#groupTitle, QLabel#itemName { font-weight: 700; }
            QLabel#groupHint { color: #788397; font-size: 12px; }
            QFrame#calendarCard, QFrame#calendarDetailCard {
                background: rgba(255, 255, 255, 154);
                border: 1px solid rgba(255, 255, 255, 225);
                border-radius: 19px;
            }
            QLabel#calendarMonth {
                color: #173b79;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#weekday {
                color: #7c8798;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton#monthButton {
                min-width: 30px;
                max-width: 30px;
                padding: 5px;
                font-size: 20px;
            }
            QPushButton#calendarDay {
                background: transparent;
                border: 0;
                padding: 0;
            }
            QFrame#historyBatchCard {
                background: rgba(255, 250, 231, 150);
                border: 1px solid rgba(255, 255, 255, 210);
                border-radius: 13px;
            }
            QLabel#historyBatchTitle {
                color: #173b79;
                font-weight: 800;
            }
            QLabel#historyItem {
                color: #5f6c81;
                background: rgba(255, 255, 255, 92);
                border-radius: 8px;
                padding: 7px;
            }
            QLabel#countPill {
                color: #214a91;
                background: rgba(230, 239, 253, 190);
                border: 1px solid rgba(255, 255, 255, 190);
                border-radius: 9px;
                padding: 2px 8px;
                font-weight: 700;
            }
            QFrame#actionBar {
                background: rgba(255, 255, 255, 170);
                border: 1px solid rgba(255, 255, 255, 225);
                border-radius: 14px;
            }
            QPushButton#primaryButton, QPushButton#primarySmall {
                color: white;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #315fa8, stop:1 #183f7c);
                border-color: rgba(255, 255, 255, 155);
            }
            QPushButton#primaryButton:hover, QPushButton#primarySmall:hover {
                color: white;
                background: #386bb7;
            }
            QPushButton#dangerButton {
                color: #8a3a2d;
                background: rgba(255, 241, 233, 185);
                border-color: rgba(255, 255, 255, 205);
            }
            QPushButton#revealButton { padding: 6px 10px; font-size: 12px; }
            QProgressBar { background: transparent; border: 0; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f2bd3e, stop:1 #315fa8);
                border-radius: 1px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 9px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(88, 108, 137, 82);
                border-radius: 4px;
                min-height: 28px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )


def run_gui(
    backend: DesktopBackend,
    *,
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run Froganize as a native Qt application and return its exit code."""
    qt = QApplication.instance()
    owns_application = qt is None
    if qt is None:
        qt = QApplication(list(argv) if argv is not None else sys.argv)
    assert isinstance(qt, QApplication)
    qt.setApplicationName("Froganize")
    qt.setApplicationDisplayName("Froganize")
    qt.setOrganizationName("Froganize")
    qt.setQuitOnLastWindowClosed(True)
    env = os.environ if environment is None else environment
    ready_file = env.get("FROGANIZE_SMOKE_READY_FILE")
    window = FroganizeWindow(
        backend,
        auto_assess=not bool(ready_file),
        environment=env,
    )
    window.show()
    window.raise_()
    window.activateWindow()
    # Keep a strong reference for the entire event loop, including macOS reactivation.
    qt._froganize_window = window  # type: ignore[attr-defined]
    if ready_file:
        ready_path = Path(ready_file).expanduser().resolve(strict=False)
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        ready_path.write_text("ready\n", encoding="utf-8")
        QTimer.singleShot(200, window.close)
    if not owns_application:
        return 0
    return qt.exec()


__all__ = [
    "DesktopBackend",
    "FroganizeWindow",
    "SCREENSHOT_AGENT_RELATIVE_PATH",
    "run_gui",
    "screenshot_agent_path",
]
