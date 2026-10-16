"""日常记录：日期列表 + Markdown 阅读器 + 内嵌音频播放条。

Markdown 的解析全部在 ``voicenote.reader``（纯函数、可单测）里完成，
本文件只负责展示与交互：

- 左侧日期列表来自 ``transcripts/`` 目录，今天带「(今日)」标记；
- ``[▶](相对路径)`` 渲染成可点击的「▶ 播放」，点击后解析成本地路径播放；
- 播放条支持 播放/暂停、进度拖动、关闭；
- 后台写盘信号到达时（仍在看今天）自动刷新，保留滚动位置。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import reader
from .player import AudioPlayer

log = logging.getLogger(__name__)


def _fmt_time(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class TranscriptsView(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._current_day: date | None = None
        self._current_path: Path | None = None
        self._player = AudioPlayer(self)
        self._build()
        self._connect_player()
        self.refresh()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # 左：历史归档
        history = QWidget(self)
        history.setFixedWidth(220)
        h_layout = QVBoxLayout(history)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(8)

        h_title = QLabel("历史归档")
        h_title.setObjectName("pageTitle")
        h_layout.addWidget(h_title)

        self._date_list = QListWidget(history)
        self._date_list.currentItemChanged.connect(self._on_day_changed)
        h_layout.addWidget(self._date_list, 1)

        btn_data_dir = QPushButton("📂 浏览记录目录", history)
        btn_data_dir.clicked.connect(self._controller.open_data_dir)
        h_layout.addWidget(btn_data_dir)

        root.addWidget(history)

        # 右：阅读区
        right = QWidget(self)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(12)

        top_bar = QHBoxLayout()
        self._date_title = QLabel("—")
        self._date_title.setObjectName("pageTitle")
        top_bar.addWidget(self._date_title)

        self._stats_label = QLabel("")
        self._stats_label.setObjectName("hint")
        top_bar.addWidget(self._stats_label)
        top_bar.addStretch(1)

        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self.refresh)
        top_bar.addWidget(btn_refresh)

        btn_copy = QPushButton("📋 复制")
        btn_copy.clicked.connect(self._on_copy)
        top_bar.addWidget(btn_copy)

        btn_external = QPushButton("↗ 外部打开")
        btn_external.clicked.connect(self._on_open_external)
        top_bar.addWidget(btn_external)

        r_layout.addLayout(top_bar)

        self._browser = QTextBrowser(right)
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor)
        r_layout.addWidget(self._browser, 1)

        r_layout.addWidget(self._build_player_dock())

        root.addWidget(right, 1)

    def _build_player_dock(self) -> QFrame:
        dock = QFrame(self)
        dock.setObjectName("playerDock")
        dock.setFixedHeight(52)
        dock.setVisible(False)
        layout = QHBoxLayout(dock)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._btn_play_pause = QPushButton("⏸")
        self._btn_play_pause.setFixedSize(32, 32)
        self._btn_play_pause.clicked.connect(self._player.toggle_pause)
        layout.addWidget(self._btn_play_pause)

        self._player_label = QLabel("—")
        self._player_label.setFixedWidth(160)
        layout.addWidget(self._player_label)

        self._slider = QSlider(Qt.Orientation.Horizontal, dock)
        self._slider.setRange(0, 0)
        self._slider.sliderReleased.connect(self._on_seek)
        layout.addWidget(self._slider, 1)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setFixedWidth(90)
        layout.addWidget(self._time_label)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setToolTip("关闭播放条")
        btn_close.clicked.connect(self._stop_playback)
        layout.addWidget(btn_close)

        self._player_dock = dock
        return dock

    def _connect_player(self) -> None:
        self._player.state_changed.connect(self._on_player_state)
        self._player.position_changed.connect(self._on_player_position)
        self._player.failed.connect(self._on_player_failed)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        transcripts_dir = self._controller.cfg.transcripts_dir
        days = reader.list_transcript_dates(transcripts_dir)

        previous = self._current_day
        self._date_list.blockSignals(True)
        self._date_list.clear()
        today = date.today()
        for day in days:
            label = f"{day:%Y-%m-%d}" + ("（今日）" if day == today else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, day)
            self._date_list.addItem(item)
        self._date_list.blockSignals(False)

        target = previous if previous in days else (today if today in days else (days[0] if days else None))
        if target is None:
            self._current_day = today
            self._current_path = reader.today_transcript_path(transcripts_dir, today)
            self._date_title.setText(f"{today:%Y-%m-%d}")
            self._stats_label.setText("暂无记录")
            self._browser.setMarkdown(
                "# 还没有任何记录\n\n开始说话后，识别出的内容会自动出现在这里。"
            )
            return

        self._select_day(target)

    def _select_day(self, day: date) -> None:
        for row in range(self._date_list.count()):
            item = self._date_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == day:
                self._date_list.setCurrentItem(item)
                return
        self.load_day(day)

    def load_day(self, day: date) -> None:
        self._current_day = day
        self._current_path = reader.transcript_path(self._controller.cfg.transcripts_dir, day)
        text = reader.read_transcript(self._current_path)
        today = date.today()

        self._date_title.setText(
            f"{day:%Y-%m-%d}" + ("（今日）" if day == today else "")
        )
        count = reader.count_records(text)
        self._stats_label.setText(f"共 {count} 条记录" if text else "暂无记录")

        scroll = self._browser.verticalScrollBar().value()
        if not text:
            self._browser.setMarkdown("# 暂无记录\n\n这一天还没有说话记录。")
            return
        self._browser.setMarkdown(reader.markdown_with_play_links(text))
        self._browser.verticalScrollBar().setValue(scroll)

    def _on_day_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        day = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(day, date):
            self.load_day(day)

    # ---------- 交互 ----------

    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() == reader.PLAY_SCHEME:
            self._play_from_href(reader.play_href_path(url.path()))
            return
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return
        if url.isLocalFile():
            self._controller.open_path(Path(url.toLocalFile()))

    def _play_from_href(self, href: str) -> None:
        if self._current_path is None:
            return
        target = reader.resolve_audio_link(self._current_path, href)
        if target is None:
            return
        if not target.is_file():
            self._controller.notify(f"音频文件不存在：{target}")
            return

        self._player.play(target)
        self._player_label.setText(target.name)
        self._player_dock.setVisible(True)

    def _stop_playback(self) -> None:
        self._player.stop()
        self._player_dock.setVisible(False)

    def _on_seek(self) -> None:
        self._player.seek(self._slider.value())
        self._btn_play_pause.setText("⏸")

    def _on_player_state(self, state: str) -> None:
        if state in ("stopped", "finished"):
            self._btn_play_pause.setText("▶")
            if state == "finished":
                self._slider.setValue(self._slider.maximum())
        elif state == "paused":
            self._btn_play_pause.setText("▶")
        else:
            self._btn_play_pause.setText("⏸")

    def _on_player_position(self, position_ms: int, total_ms: int) -> None:
        self._slider.setMaximum(max(0, total_ms))
        if not self._slider.isSliderDown():
            self._slider.setValue(position_ms)
        self._time_label.setText(f"{_fmt_time(position_ms)} / {_fmt_time(total_ms)}")

    def _on_player_failed(self, message: str) -> None:
        self._controller.notify(message)
        self._player_dock.setVisible(False)

    def _on_copy(self) -> None:
        if self._current_path is None:
            return
        text = reader.read_transcript(self._current_path)
        QGuiApplication.clipboard().setText(reader.body_without_audio_links(text))
        self._controller.notify("已复制当前记录到剪贴板")

    def _on_open_external(self) -> None:
        if self._current_path is None:
            return
        path = self._current_path
        if not path.exists():
            self._controller.notify("当天还没有记录文件")
            return
        self._controller.open_path(path)

    # ---------- 后台信号 ----------

    def on_transcript_saved(self, path: str) -> None:
        """新记录写入：如果正在看今天，就地刷新（保留滚动位置）。"""
        saved = Path(path)
        if self._current_day != date.today():
            return
        if self._current_path is not None and saved != self._current_path:
            return
        self.load_day(date.today())
