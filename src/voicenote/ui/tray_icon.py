"""系统托盘：QSystemTrayIcon 原生实现（替代旧 pystray）。

菜单结构与设计稿 §4.1 对齐：

    状态指示（只读）
    ├── 打开主界面 → 日常记录
    ├── 选项设置 → 本地模型
    ├── API 配置 → 云端 API
    ├── 暂停/恢复监听
    ├── 开机自启（勾选）
    ├── 打开数据目录
    └── 退出 VoiceNote

左键单击/双击托盘图标 = 打开主界面。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME, __version__
from .. import autostart
from ..status import COLORS, TITLES, IconState

log = logging.getLogger(__name__)


def make_state_icon(state: IconState) -> QIcon:
    """按状态色画一个圆点图标（不依赖外部资源文件）。"""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(*COLORS[state])
        painter.setBrush(color)
        painter.setPen(color)
        painter.drawEllipse(8, 8, size - 16, size - 16)
    finally:
        painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """托盘图标 + 右键菜单。所有动作都在 Qt 主线程执行。"""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._state = IconState.LISTENING

        self.setIcon(make_state_icon(self._state))
        self.setToolTip(TITLES[self._state])
        self._build_menu()
        self.activated.connect(self._on_activated)

    # ---------- 菜单 ----------

    def _build_menu(self) -> None:
        menu = QMenu()

        self._status_action = QAction(self._status_text(), menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        menu.addSeparator()

        act_open = QAction("📝 打开主界面", menu)
        act_open.triggered.connect(lambda: self._controller.show_page("transcripts"))
        menu.addAction(act_open)

        act_models = QAction("⚙️ 选项设置…", menu)
        act_models.triggered.connect(lambda: self._controller.show_page("models"))
        menu.addAction(act_models)

        act_api = QAction("🔑 API 配置…", menu)
        act_api.triggered.connect(lambda: self._controller.show_page("api"))
        menu.addAction(act_api)

        menu.addSeparator()

        self._pause_action = QAction(self._pause_text(), menu)
        self._pause_action.triggered.connect(self._on_toggle_pause)
        menu.addAction(self._pause_action)

        self._autostart_action = QAction("开机自启动", menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(self._autostart_enabled())
        self._autostart_action.triggered.connect(self._on_toggle_autostart)
        menu.addAction(self._autostart_action)

        act_data = QAction("📂 打开数据目录", menu)
        act_data.triggered.connect(self._controller.open_data_dir)
        menu.addAction(act_data)

        menu.addSeparator()

        act_quit = QAction("❌ 退出 VoiceNote", menu)
        act_quit.triggered.connect(self._controller.shutdown)
        menu.addAction(act_quit)

        self._menu = menu
        self.setContextMenu(menu)

    def refresh(self) -> None:
        self._status_action.setText(self._status_text())
        self._pause_action.setText(self._pause_text())
        self._autostart_action.setChecked(self._autostart_enabled())

    def _status_text(self) -> str:
        title = TITLES[self._state].replace("VoiceNote — ", "")
        try:
            engine = self._controller.active_engine_name
        except Exception:
            engine = ""
        suffix = f"（{engine}）" if engine else ""
        return f"🟢 {APP_NAME} v{__version__} — {title}{suffix}"

    def _pause_text(self) -> str:
        return "▶️ 恢复监听" if self._controller.paused else "⏸️ 暂停监听"

    # ---------- 状态 ----------

    def set_state(self, state: IconState) -> None:
        self._state = state
        self.setIcon(make_state_icon(state))
        self.setToolTip(TITLES[state])
        self.refresh()

    # ---------- 通知 ----------

    def notify(self, message: str, title: str | None = None) -> None:
        """弹出系统托盘气泡通知。"""
        t = title or APP_NAME
        try:
            self.showMessage(
                t,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        except Exception as exc:
            log.debug("托盘消息弹出失败：%s", exc)

    # ---------- 事件 ----------

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._controller.show_page("transcripts")

    def _on_toggle_pause(self) -> None:
        if self._controller.paused:
            self._controller.resume()
        else:
            self._controller.pause()
        self.refresh()

    def _on_toggle_autostart(self) -> None:
        try:
            if self._autostart_enabled():
                autostart.disable()
            else:
                autostart.enable()
        except ImportError:
            self._controller.notify("开机自启仅支持 Windows")
        except Exception as exc:
            log.exception("切换开机自启失败")
            self._controller.notify(f"切换开机自启失败：{exc}")
        self.refresh()

    @staticmethod
    def _autostart_enabled() -> bool:
        try:
            return autostart.is_enabled()
        except Exception:
            return False
