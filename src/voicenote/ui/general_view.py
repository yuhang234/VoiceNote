"""录音与系统设置：输入设备、VAD 分段参数、开机自启、关闭行为。

所有改动点「保存设置」后写回 config.toml；涉及音频流本身（设备、采样率）的
改动需要重启程序才能完全生效，界面会给出明确提示。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import autostart
from ..config import CLOSE_ACTIONS

log = logging.getLogger(__name__)

_CLOSE_CHOICES = (
    ("最小化到托盘（继续录音）", "minimize_to_tray"),
    ("退出程序", "exit"),
)


class GeneralSettingsView(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._build()
        self.load_from_config()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("录音与系统设置")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        root.addWidget(self._build_audio_group())
        root.addWidget(self._build_vad_group())
        root.addWidget(self._build_system_group())

        data_row = QHBoxLayout()
        self._data_label = QLabel("")
        self._data_label.setObjectName("hint")
        data_row.addWidget(self._data_label, 1)
        btn_open_data = QPushButton("📂 打开数据目录")
        btn_open_data.clicked.connect(self._controller.open_data_dir)
        data_row.addWidget(btn_open_data)
        root.addLayout(data_row)

        root.addStretch(1)

        bottom = QHBoxLayout()
        self._hint = QLabel("")
        self._hint.setObjectName("hint")
        bottom.addWidget(self._hint, 1)
        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._on_save)
        bottom.addWidget(btn_save)
        root.addLayout(bottom)

    def _build_audio_group(self) -> QGroupBox:
        group = QGroupBox("录音")
        form = QFormLayout(group)

        self._check_audio_enabled = QCheckBox("留存音频（关闭后只保存文字）")
        form.addRow("", self._check_audio_enabled)

        self._combo_device = QComboBox()
        self._combo_device.setEditable(True)
        form.addRow("输入设备（子串匹配，留空=系统默认）：", self._combo_device)

        self._spin_sample_rate = QSpinBox()
        self._spin_sample_rate.setRange(8000, 48000)
        self._spin_sample_rate.setSingleStep(1000)
        self._spin_sample_rate.setSuffix(" Hz")
        form.addRow("采样率（建议 16000）：", self._spin_sample_rate)
        return group

    def _build_vad_group(self) -> QGroupBox:
        group = QGroupBox("VAD 分段")
        form = QFormLayout(group)

        self._spin_threshold = QDoubleSpinBox()
        self._spin_threshold.setRange(0.05, 0.95)
        self._spin_threshold.setSingleStep(0.05)
        self._spin_threshold.setDecimals(2)
        form.addRow("语音概率阈值：", self._spin_threshold)

        self._spin_min_speech = QSpinBox()
        self._spin_min_speech.setRange(50, 5000)
        self._spin_min_speech.setSuffix(" ms")
        form.addRow("最短语音（更短的丢弃）：", self._spin_min_speech)

        self._spin_min_silence = QSpinBox()
        self._spin_min_silence.setRange(100, 5000)
        self._spin_min_silence.setSuffix(" ms")
        form.addRow("静音断句阈值：", self._spin_min_silence)

        self._spin_max_segment = QSpinBox()
        self._spin_max_segment.setRange(5, 120)
        self._spin_max_segment.setSuffix(" 秒")
        form.addRow("单段最长时长：", self._spin_max_segment)
        return group

    def _build_system_group(self) -> QGroupBox:
        group = QGroupBox("系统")
        form = QFormLayout(group)

        self._check_autostart = QCheckBox("开机自启动（仅 Windows）")
        self._check_autostart.setEnabled(self._autostart_supported())
        form.addRow("", self._check_autostart)

        self._check_open_ui = QCheckBox("启动时自动打开主界面（不勾选=仅托盘静默启动）")
        form.addRow("", self._check_open_ui)

        self._combo_close = QComboBox()
        for label, value in _CLOSE_CHOICES:
            self._combo_close.addItem(label, value)
        form.addRow("关闭主窗口时：", self._combo_close)
        return group

    # ---------- 数据 ----------

    @staticmethod
    def _autostart_supported() -> bool:
        try:
            import winreg  # noqa: F401

            return True
        except ImportError:
            return False

    def _populate_devices(self, current: str) -> None:
        self._combo_device.clear()
        self._combo_device.addItem("", "")
        try:
            import sounddevice as sd

            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) < 1:
                    continue
                self._combo_device.addItem(f"#{idx} {dev['name']}", dev["name"])
        except Exception as exc:
            log.debug("枚举音频设备失败：%s", exc)
        self._combo_device.setCurrentText(current)

    def load_from_config(self) -> None:
        cfg = self._controller.cfg

        self._check_audio_enabled.setChecked(cfg.audio.enabled)
        self._populate_devices(cfg.audio.device)
        self._spin_sample_rate.setValue(cfg.audio.sample_rate)

        self._spin_threshold.setValue(cfg.vad.speech_threshold)
        self._spin_min_speech.setValue(cfg.vad.min_speech_ms)
        self._spin_min_silence.setValue(cfg.vad.min_silence_ms)
        self._spin_max_segment.setValue(cfg.vad.max_segment_s)

        try:
            self._check_autostart.setChecked(autostart.is_enabled())
        except Exception:
            self._check_autostart.setChecked(False)
        self._check_open_ui.setChecked(cfg.general.open_ui_on_startup)
        index = self._combo_close.findData(cfg.general.close_action)
        self._combo_close.setCurrentIndex(max(0, index))

        self._data_label.setText(f"数据目录：{cfg.data_dir}")
        self._hint.setText("")

    # ---------- 保存 ----------

    def _on_save(self) -> None:
        cfg = self._controller.cfg
        device_changed = False

        cfg.audio.enabled = self._check_audio_enabled.isChecked()

        new_device = self._combo_device.currentText().strip()
        if new_device != cfg.audio.device:
            device_changed = True
            cfg.audio.device = new_device
            # 用户可能选了 "#2 xxx" 这种带序号的展示文本，回退成纯名字。
            for idx in range(self._combo_device.count()):
                if self._combo_device.itemText(idx) == new_device:
                    cfg.audio.device = self._combo_device.itemData(idx) or ""
                    break

        if self._spin_sample_rate.value() != cfg.audio.sample_rate:
            device_changed = True
            cfg.audio.sample_rate = self._spin_sample_rate.value()

        cfg.vad.speech_threshold = self._spin_threshold.value()
        cfg.vad.min_speech_ms = self._spin_min_speech.value()
        cfg.vad.min_silence_ms = self._spin_min_silence.value()
        cfg.vad.max_segment_s = self._spin_max_segment.value()

        cfg.general.open_ui_on_startup = self._check_open_ui.isChecked()
        cfg.general.close_action = self._combo_close.currentData()

        # 开机自启：Windows 下立即生效；其它平台勾选框是禁用的。
        if self._autostart_supported():
            try:
                want = self._check_autostart.isChecked()
                if want != autostart.is_enabled():
                    if want:
                        autostart.enable()
                    else:
                        autostart.disable()
            except Exception as exc:
                log.exception("设置开机自启失败")
                self._controller.notify(f"设置开机自启失败：{exc}")

        path = self._controller.save_config()
        if device_changed:
            self._hint.setText("音频设备/采样率改动需要重启程序后生效")
        elif path:
            self._hint.setText(f"已保存：{path}")
        self._controller.notify("设置已保存")
