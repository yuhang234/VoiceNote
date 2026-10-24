"""本地模型管理：缓存状态、下载/重试/取消、一键热切换、清理。

状态完全由真实缓存决定（``whisper_model_cached``），不做乐观假设：
点「下载」直到 hub 快照真正落盘、并能找到权重文件之后，卡片才会变成「已就绪」。
SenseVoice 卡片明确显示"引擎未实现"，不提供可点击的假入口。
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import models
from ..config import AsrConfig
from .workers import EngineSwitchWorker, ModelDownloadWorker

_DEVICE_CHOICES = (("CUDA GPU（推荐）", "cuda"), ("CPU（较慢）", "cpu"))
_COMPUTE_CHOICES = ("int8_float16", "int8", "float16", "float32")
_LANGUAGE_CHOICES = (("自动检测（中英混说首选）", ""), ("zh（中文）", "zh"), ("en（英文）", "en"))


def _free_disk_text(path: Path) -> str:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
        return f"磁盘剩余：{usage.free / 1e9:.1f} GB"
    except OSError:
        return "磁盘剩余：未知"


def _human_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "—"
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / 1024 ** 3:.2f} GB"
    return f"{num_bytes / 1024 ** 2:.0f} MB"


class _ModelCard(QFrame):
    """单个模型卡片：状态标签 + 进度条 + 操作按钮。"""

    def __init__(self, spec: models.ModelSpec, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.spec = spec

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        self._badge = QLabel("")
        self._badge.setFixedWidth(84)
        title_row.addWidget(self._badge)

        name = QLabel(f"{spec.engine}/{spec.id}（{spec.label}）")
        name.setStyleSheet("font-weight: 600;")
        title_row.addWidget(name)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        meta = QLabel(
            f"体积约 {_human_size(spec.size_mb * 1024 ** 2)} ｜ {spec.params_m}M 参数 ｜ "
            f"{spec.speed_hint}\n{spec.description}"
        )
        meta.setObjectName("hint")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        self._reason = QLabel(f"⚠️ {spec.unavailable_reason}")
        self._reason.setWordWrap(True)
        self._reason.setStyleSheet("color: #ca8a04;")
        self._reason.setVisible(not spec.available)
        layout.addWidget(self._reason)

        bottom = QHBoxLayout()
        self._status = QLabel("状态：检查中…")
        bottom.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setFixedWidth(160)
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        bottom.addWidget(self._progress)
        bottom.addStretch(1)

        self._btn_primary = QPushButton("切换生效")
        self._btn_primary.clicked.connect(self._on_primary)
        bottom.addWidget(self._btn_primary)

        self._btn_download = QPushButton("⬇ 下载模型")
        self._btn_download.clicked.connect(self._on_download)
        bottom.addWidget(self._btn_download)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setVisible(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        bottom.addWidget(self._btn_cancel)

        self._btn_cleanup = QPushButton("🗑 清理")
        self._btn_cleanup.clicked.connect(self._on_cleanup)
        bottom.addWidget(self._btn_cleanup)

        layout.addLayout(bottom)

        self._view: "LocalModelsView | None" = None

    def bind(self, view: "LocalModelsView") -> None:
        self._view = view

    # 按钮 → 视图（通过父视图发信号，避免卡片自己持有业务逻辑）
    def _on_primary(self) -> None:
        if self._view is not None:
            self._view.switch_to_model(self.spec.id)

    def _on_download(self) -> None:
        if self._view is not None:
            self._view.start_download(self.spec.id)

    def _on_cancel(self) -> None:
        if self._view is not None:
            self._view.cancel_download(self.spec.id)

    def _on_cleanup(self) -> None:
        if self._view is not None:
            self._view.cleanup_model(self.spec.id)

    # 状态刷新
    def update_status(
        self,
        *,
        cached: bool,
        active: bool,
        downloading: bool,
        error: str = "",
        percent: float = 0.0,
        speed_mb_s: float = 0.0,
        size_bytes: int = 0,
        available_override: bool | None = None,
    ) -> None:
        is_parakeet = self.spec.engine == "parakeet"
        available = (
            self.spec.available if available_override is None else available_override
        )
        self._reason.setVisible(not available)
        show_download = False

        if downloading:
            self._badge.setText("⏬ 下载中")
            self._status.setText(
                f"状态：正在下载 {percent:.0f}%"
                + (f"（{speed_mb_s:.1f} MB/s）" if speed_mb_s else "")
            )
            self._progress.setVisible(True)
            self._progress.setValue(int(min(100.0, max(0.0, percent))))
            self._btn_cancel.setVisible(True)
        else:
            self._progress.setVisible(False)
            self._btn_cancel.setVisible(False)
            if not available:
                self._badge.setText("⛔ 不可用")
                self._status.setText(
                    f"状态：{self.spec.unavailable_reason}"
                    if self.spec.unavailable_reason
                    else "状态：当前环境不可用"
                )
            elif error:
                self._badge.setText("⚠️ 失败")
                self._status.setText(f"状态：{error}")
                show_download = not is_parakeet
            elif active:
                self._badge.setText("✅ 当前使用")
                self._status.setText(
                    f"状态：已就绪（{_human_size(size_bytes)}）"
                    if size_bytes
                    else "状态：已就绪（已缓存）"
                )
            elif cached:
                self._badge.setText("💾 已缓存")
                self._status.setText(
                    f"状态：已就绪（{_human_size(size_bytes)}）"
                    if size_bytes
                    else "状态：已就绪（已缓存）"
                )
            elif is_parakeet:
                # NeMo 在首次切换时自动下载，不需要手动点“下载模型”
                self._badge.setText("— 待下载")
                self._status.setText("状态：首次切换时由 NeMo 自动下载")
            else:
                self._badge.setText("— 未下载")
                self._status.setText("状态：未下载")
                show_download = True

        self._btn_download.setVisible(show_download)
        self._btn_download.setText("⬇ 下载模型")
        # Parakeet 不缓存也能直接切换（切换时 NeMo 自动下载）
        self._btn_primary.setEnabled(
            available and not active and not downloading and (cached or is_parakeet)
        )
        self._btn_cleanup.setEnabled(available and cached and not active and not downloading)
        self._btn_download.setEnabled(available and not downloading)
        self._btn_primary.setToolTip(
            "" if available else "该模型在当前环境不可用（请先安装对应引擎依赖）"
        )


class LocalModelsView(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._cards: dict[str, _ModelCard] = {}
        self._workers: dict[str, ModelDownloadWorker] = {}
        self._switch_worker: EngineSwitchWorker | None = None
        self._errors: dict[str, str] = {}
        self._progress: dict[str, tuple[float, float]] = {}
        self._build()
        self.refresh()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("本地语音识别模型（ASR）")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        desc = QLabel(
            "所有模型离线运行于本机，语音不出本机。默认下载源可在 config.toml 的 "
            "general.hf_endpoint 调整（当前生效值见下方）。"
        )
        desc.setObjectName("hint")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # 存储路径栏
        storage = QFrame(self)
        storage.setObjectName("cardFrame")
        s_layout = QHBoxLayout(storage)
        s_layout.setContentsMargins(12, 8, 12, 8)
        self._path_label = QLabel("")
        s_layout.addWidget(self._path_label)
        s_layout.addStretch(1)
        self._disk_label = QLabel("")
        s_layout.addWidget(self._disk_label)

        btn_open_dir = QPushButton("打开目录")
        btn_open_dir.clicked.connect(self._open_models_dir)
        s_layout.addWidget(btn_open_dir)

        btn_refresh = QPushButton("🔄 刷新状态")
        btn_refresh.clicked.connect(self.refresh)
        s_layout.addWidget(btn_refresh)
        root.addWidget(storage)

        # 卡片滚动区
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(10)

        for spec in models.LOCAL_MODELS:
            card = _ModelCard(spec, container)
            card.bind(self)
            self._cards[spec.id] = card
            cards_layout.addWidget(card)
        cards_layout.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        root.addWidget(self._build_hardware_group())

        bottom = QHBoxLayout()
        btn_defaults = QPushButton("恢复默认")
        btn_defaults.clicked.connect(self._reset_defaults)
        bottom.addWidget(btn_defaults)
        bottom.addStretch(1)
        self._btn_apply = QPushButton("应用并保存配置")
        self._btn_apply.setObjectName("primary")
        self._btn_apply.clicked.connect(self._apply_settings)
        bottom.addWidget(self._btn_apply)
        root.addLayout(bottom)

    def _build_hardware_group(self) -> QGroupBox:
        group = QGroupBox("硬件与推理调优")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self._combo_device = QComboBox()
        for label, value in _DEVICE_CHOICES:
            self._combo_device.addItem(label, value)
        grid.addWidget(QLabel("运行设备："), 0, 0)
        grid.addWidget(self._combo_device, 0, 1)

        self._combo_compute = QComboBox()
        for value in _COMPUTE_CHOICES:
            self._combo_compute.addItem(value, value)
        grid.addWidget(QLabel("计算精度："), 0, 2)
        grid.addWidget(self._combo_compute, 0, 3)

        self._combo_language = QComboBox()
        for label, value in _LANGUAGE_CHOICES:
            self._combo_language.addItem(label, value)
        grid.addWidget(QLabel("识别语言："), 1, 0)
        grid.addWidget(self._combo_language, 1, 1)

        self._spin_beam = QSpinBox()
        self._spin_beam.setRange(1, 5)
        grid.addWidget(QLabel("解码束宽："), 1, 2)
        grid.addWidget(self._spin_beam, 1, 3)
        return group

    # ---------- 状态 ----------

    def refresh(self) -> None:
        cfg = self._controller.cfg
        cache_dir = models.hf_hub_cache_dir()
        self._path_label.setText(f"模型缓存目录：{cache_dir}")
        self._disk_label.setText(_free_disk_text(cache_dir))

        for model_id, card in self._cards.items():
            engine = models.engine_for_model(model_id)
            active = cfg.asr.model == model_id and cfg.asr.engine == engine
            cached = models.model_cached(model_id)
            size = models.model_downloaded_size(model_id) if cached else 0
            percent, speed = self._progress.get(model_id, (0.0, 0.0))
            available_override = (
                models.parakeet_installed() if engine == "parakeet" else None
            )
            card.update_status(
                cached=cached,
                active=active,
                downloading=model_id in self._workers,
                error=self._errors.get(model_id, ""),
                percent=percent,
                speed_mb_s=speed,
                size_bytes=size,
                available_override=available_override,
            )

        # 硬件控件回填（不覆盖用户尚未应用的选择？简单起见以配置为准）
        asr = cfg.asr
        index = self._combo_device.findData(asr.device)
        if index >= 0:
            self._combo_device.setCurrentIndex(index)
        index = self._combo_compute.findData(asr.compute_type)
        if index >= 0:
            self._combo_compute.setCurrentIndex(index)
        index = self._combo_language.findData(asr.language)
        if index >= 0:
            self._combo_language.setCurrentIndex(index)
        self._spin_beam.setValue(asr.beam_size)

    def _open_models_dir(self) -> None:
        self._controller.open_path(models.hf_hub_cache_dir())

    def _reset_defaults(self) -> None:
        defaults = AsrConfig()
        index = self._combo_device.findData(defaults.device)
        if index >= 0:
            self._combo_device.setCurrentIndex(index)
        index = self._combo_compute.findData(defaults.compute_type)
        if index >= 0:
            self._combo_compute.setCurrentIndex(index)
        self._combo_language.setCurrentIndex(0)
        self._spin_beam.setValue(defaults.beam_size)

    # ---------- 下载 ----------

    def start_download(self, model_id: str) -> None:
        if model_id in self._workers:
            return
        if models.engine_for_model(model_id) == "parakeet":
            self._controller.notify("Parakeet 模型会在首次切换时由 NeMo 自动下载")
            return
        self._errors.pop(model_id, None)
        worker = ModelDownloadWorker(
            model_id,
            hf_endpoint=self._controller.cfg.general.hf_endpoint,
            parent=self,
        )
        worker.progress_changed.connect(self._on_download_progress)
        worker.download_finished.connect(self._on_download_finished)
        self._workers[model_id] = worker
        worker.start()
        self.refresh()

    def cancel_download(self, model_id: str) -> None:
        worker = self._workers.get(model_id)
        if worker is not None:
            worker.cancel()

    def _on_download_progress(self, model_id: str, percent: float, speed_mb_s: float) -> None:
        self._progress[model_id] = (percent, speed_mb_s)
        card = self._cards.get(model_id)
        if card is not None:
            card.update_status(
                cached=False,
                active=False,
                downloading=True,
                percent=percent,
                speed_mb_s=speed_mb_s,
            )

    def _on_download_finished(self, model_id: str, ok: bool, message: str) -> None:
        worker = self._workers.pop(model_id, None)
        if worker is not None:
            worker.deleteLater()
        if ok:
            self._errors.pop(model_id, None)
            self._progress.pop(model_id, None)
            self._controller.notify(f"模型 {model_id} 下载完成，可一键切换")
        else:
            if "取消" in message:
                self._progress.pop(model_id, None)
            else:
                self._errors[model_id] = message
                self._controller.notify(f"模型 {model_id} 下载失败：{message}")
        self.refresh()

    # ---------- 清理 ----------

    def cleanup_model(self, model_id: str) -> None:
        cfg = self._controller.cfg
        if cfg.asr.model == model_id and cfg.asr.engine == models.engine_for_model(model_id):
            self._controller.notify("当前正在使用的模型不能删除，请先切换到其他模型")
            return

        answer = QMessageBox.question(
            self,
            "清理模型缓存",
            f"确定要删除 {model_id} 的本地缓存吗？再次使用需要重新下载。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if models.delete_model_cache(model_id):
            self._controller.notify(f"已删除 {model_id} 的缓存")
        self.refresh()

    # ---------- 切换 ----------

    def _build_asr_config(self, model_id: str) -> AsrConfig:
        cfg = self._controller.cfg
        return replace(
            cfg.asr,
            engine=models.engine_for_model(model_id),
            model=model_id,
            device=self._combo_device.currentData(),
            compute_type=self._combo_compute.currentData(),
            language=self._combo_language.currentData(),
            beam_size=self._spin_beam.value(),
        )

    def switch_to_model(self, model_id: str) -> None:
        self._switch(self._build_asr_config(model_id), f"已切换到 {model_id}")

    def _apply_settings(self) -> None:
        cfg = self._controller.cfg
        model_id = cfg.asr.model if cfg.asr.model in self._cards else "large-v3-turbo"
        self._switch(self._build_asr_config(model_id), "设置已应用并保存")

    def _switch(self, new_asr_cfg: AsrConfig, success_message: str) -> None:
        if self._switch_worker is not None and self._switch_worker.isRunning():
            self._controller.notify("上一次切换还在进行中，请稍候")
            return
        self._btn_apply.setEnabled(False)
        worker = EngineSwitchWorker(
            self._controller,
            new_asr_cfg,
            self._controller.api_key(),
            parent=self,
        )
        worker.finished_result.connect(
            lambda ok, detail: self._on_switch_done(ok, detail, success_message)
        )
        self._switch_worker = worker
        worker.start()

    def _on_switch_done(self, ok: bool, detail: str, success_message: str) -> None:
        self._btn_apply.setEnabled(True)
        if ok:
            self._controller.save_config()
            self._controller.notify(success_message)
            self.refresh()
        else:
            self._controller.notify(f"切换失败：{detail}")
