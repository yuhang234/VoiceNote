"""主窗口：统一外壳（侧边栏导航 + QStackedWidget 内容区）。

设计稿 §3.2 / §5.1：

- 左侧固定宽度侧边栏：品牌区、状态胶囊、四个导航项、当前引擎卡片、快捷暂停；
- 右侧内容区在四个页面之间切换：日常记录 / 本地模型 / API 配置 / 录音与系统；
- 关闭按钮默认"隐藏到托盘"（``general.close_action`` 可改为退出），
  绝不静默杀掉还在后台录音的进程。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..status import COLORS, LABELS, IconState
from .api_config_view import ApiConfigView
from .general_view import GeneralSettingsView
from .local_models_view import LocalModelsView
from .reader_view import TranscriptsView
from .styles import QSS

PAGES = ("transcripts", "models", "api", "settings")


def ensure_qt_app(argv: list[str] | None = None) -> QApplication:
    """拿到（必要时创建）全局 QApplication。

    托盘应用不能在最后一个窗口关闭时退出 —— 关窗只是隐藏到托盘。
    """
    existing = QApplication.instance()
    if existing is not None:
        return existing
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    return app


class MainWindow(QMainWindow):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._tray = None

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1100, 720)
        self.setMinimumSize(960, 650)

        self._build()
        self.on_state_changed(self._controller.state)
        self.refresh_engine_label()

    # ---------- 构建 ----------

    def _build(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self._stack = QStackedWidget(central)
        self._transcripts_view = TranscriptsView(self._controller, self._stack)
        self._models_view = LocalModelsView(self._controller, self._stack)
        self._api_view = ApiConfigView(self._controller, self._stack)
        self._settings_view = GeneralSettingsView(self._controller, self._stack)
        self._stack.addWidget(self._transcripts_view)
        self._stack.addWidget(self._models_view)
        self._stack.addWidget(self._api_view)
        self._stack.addWidget(self._settings_view)
        root.addWidget(self._stack, 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        icon = QLabel("🎙")
        icon.setFixedSize(28, 28)
        brand.addWidget(icon)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        brand.addWidget(title)
        brand.addStretch(1)
        layout.addLayout(brand)

        version = QLabel(f"v{__version__}")
        version.setObjectName("hint")
        layout.addWidget(version)

        self._status_pill = QLabel(LABELS[IconState.LISTENING])
        self._status_pill.setObjectName("statusPill")
        layout.addWidget(self._status_pill)

        layout.addSpacing(6)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        nav_items = (
            ("transcripts", "📝  日常记录"),
            ("models", "🤖  本地模型"),
            ("api", "🔑  API 配置"),
            ("settings", "⚙️  录音与系统"),
        )
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, text in nav_items:
            btn = QPushButton(text)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            self._nav_group.addButton(btn)
            layout.addWidget(btn)
            self._nav_buttons[key] = btn
            btn.clicked.connect(lambda _checked=False, k=key: self.show_page(k))
        self._nav_buttons["transcripts"].setChecked(True)

        layout.addStretch(1)

        engine_card = QFrame()
        engine_card.setObjectName("miniCard")
        engine_layout = QVBoxLayout(engine_card)
        engine_layout.setContentsMargins(8, 8, 8, 8)
        engine_layout.setSpacing(2)
        engine_header = QLabel("当前引擎：")
        engine_header.setObjectName("hint")
        engine_layout.addWidget(engine_header)
        self._engine_label = QLabel("—")
        self._engine_label.setWordWrap(True)
        engine_layout.addWidget(self._engine_label)
        layout.addWidget(engine_card)

        self._btn_quick_pause = QPushButton("⏸ 暂停监听")
        self._btn_quick_pause.clicked.connect(self._on_quick_pause)
        layout.addWidget(self._btn_quick_pause)
        return sidebar

    # ---------- 对外接口 ----------

    def attach_tray(self, tray) -> None:
        self._tray = tray

    def show_page(self, page: str) -> None:
        if page not in PAGES:
            page = "transcripts"
        self._stack.setCurrentIndex(PAGES.index(page))
        button = self._nav_buttons.get(page)
        if button is not None:
            button.setChecked(True)
        self.refresh_engine_label()

        if page == "transcripts":
            self._transcripts_view.refresh()
        elif page == "models":
            self._models_view.refresh()
        elif page == "api":
            self._api_view.load_from_config()
        elif page == "settings":
            self._settings_view.load_from_config()

    def refresh_engine_label(self) -> None:
        self._engine_label.setText(self._controller.active_engine_name)

    def on_state_changed(self, state: IconState) -> None:
        self._status_pill.setText(LABELS.get(state, ""))
        color = COLORS.get(state, (110, 119, 129))
        self._status_pill.setStyleSheet(
            f"color: rgb({color[0]}, {color[1]}, {color[2]}); font-weight: 600;"
        )
        self._btn_quick_pause.setText(
            "▶ 恢复监听" if self._controller.paused else "⏸ 暂停监听"
        )
        if state in (IconState.LISTENING, IconState.TRANSCRIBING):
            self.refresh_engine_label()

    def on_notification(self, message: str) -> None:
        # 主窗口可见时把消息放到状态栏；不可见时只靠托盘气泡（tray 已连接）。
        if self.isVisible():
            self.statusBar().showMessage(message, 8000)

    def on_transcript_saved(self, path: str) -> None:
        self._transcripts_view.on_transcript_saved(path)

    # ---------- 事件 ----------

    def _on_quick_pause(self) -> None:
        if self._controller.paused:
            self._controller.resume()
        else:
            self._controller.pause()
        self.on_state_changed(self._controller.state)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 命名
        close_action = getattr(
            self._controller.cfg.general, "close_action", "minimize_to_tray"
        )
        if close_action == "minimize_to_tray":
            event.ignore()
            self.hide()
            if self._tray is not None:
                self._tray.notify(
                    "VoiceNote 已最小化到托盘，录音仍在后台进行。"
                    "彻底退出请使用托盘菜单。"
                )
        else:
            event.accept()
            self._controller.shutdown()
