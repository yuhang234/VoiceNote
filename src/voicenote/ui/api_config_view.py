"""云端 API 配置：厂商模板、连接参数、密钥、连通性测试。

- API Key 只进 ``state/secrets.json``（见 secret_store），绝不写进 config.toml；
- 模板覆盖 OpenAI / SiliconFlow / Groq 三条完全兼容路径；DashScope 明确标注
  "私有协议、当前不可用"，不做假支持；
- "测试连通性"在后台线程里真实发一次请求，状态与错误提示对齐设计稿 §8.3。
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_module
from ..asr.openai_api_engine import API_TEMPLATES, ApiTemplate, ConnectionTestResult
from ..config import ApiConfig
from ..secret_store import DEFAULT_PROFILE
from .workers import ConnectionTestWorker, EngineSwitchWorker


class ApiConfigView(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._test_worker: ConnectionTestWorker | None = None
        self._switch_worker: EngineSwitchWorker | None = None
        self._build()
        self.load_from_config()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("云端 ASR 大模型 API 配置")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        desc = QLabel(
            "配置第三方云厂商的语音识别服务，低配电脑也能快速转写。"
            "当前支持所有 OpenAI 兼容协议的服务（OpenAI / 硅基流动 / Groq / 自建网关）。"
        )
        desc.setObjectName("hint")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # 引擎模式
        mode_group = QGroupBox("转写引擎模式")
        mode_layout = QHBoxLayout(mode_group)
        self._radio_local = QRadioButton("使用本地离线模型")
        self._radio_api = QRadioButton("使用云端 API 引擎")
        mode_layout.addWidget(self._radio_local)
        mode_layout.addWidget(self._radio_api)
        mode_layout.addStretch(1)
        root.addWidget(mode_group)

        # 模板
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("主流厂商模板："))
        self._combo_template = QComboBox()
        for tpl in API_TEMPLATES:
            self._combo_template.addItem(tpl.label, tpl.id)
        template_row.addWidget(self._combo_template, 1)
        btn_apply_template = QPushButton("填充此模板")
        btn_apply_template.clicked.connect(self._on_apply_template)
        template_row.addWidget(btn_apply_template)
        root.addLayout(template_row)

        self._template_note = QLabel("")
        self._template_note.setObjectName("hint")
        self._template_note.setWordWrap(True)
        root.addWidget(self._template_note)

        # 表单
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        form = QFormLayout(form_container)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(10)

        self._edit_base_url = QLineEdit()
        form.addRow("服务接口地址 (Base URL)：", self._edit_base_url)

        self._edit_endpoint = QLineEdit()
        self._edit_endpoint.setToolTip("OpenAI 音频转写规范固定为 /audio/transcriptions")
        form.addRow("端点相对路径：", self._edit_endpoint)

        self._edit_model = QLineEdit()
        form.addRow("识别模型标识符 (Model)：", self._edit_model)

        key_row = QHBoxLayout()
        self._edit_key = QLineEdit()
        self._edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._edit_key, 1)
        self._btn_show_key = QPushButton("👁 显示")
        self._btn_show_key.setCheckable(True)
        self._btn_show_key.toggled.connect(self._on_toggle_key)
        key_row.addWidget(self._btn_show_key)
        form.addRow("API 密钥 (API Key)：", key_row)

        key_hint = QLabel("密钥仅保存在本地 state/secrets.json，不写入 config.toml，也不会进日志。")
        key_hint.setObjectName("hint")
        key_hint.setWordWrap(True)
        form.addRow("", key_hint)

        self._spin_timeout = QSpinBox()
        self._spin_timeout.setRange(5, 120)
        self._spin_timeout.setSuffix(" 秒")
        form.addRow("请求超时：", self._spin_timeout)

        self._edit_text_path = QLineEdit()
        self._edit_text_path.setToolTip("例如 text 或 results[0].transcript")
        form.addRow("响应文本提取路径：", self._edit_text_path)

        self._edit_headers = QTextEdit()
        self._edit_headers.setMaximumHeight(60)
        self._edit_headers.setPlaceholderText('{"Authorization": "Bearer {API_KEY}"}')
        form.addRow("自定义请求头 (JSON，可选)：", self._edit_headers)

        scroll.setWidget(form_container)
        root.addWidget(scroll, 1)

        # 连通性测试
        test_card = QFrame(self)
        test_card.setObjectName("cardFrame")
        t_layout = QHBoxLayout(test_card)
        t_layout.setContentsMargins(12, 8, 12, 8)
        self._btn_test = QPushButton("⚡ 测试 API 连通性")
        self._btn_test.clicked.connect(self._on_test)
        t_layout.addWidget(self._btn_test)
        self._test_label = QLabel("未测试")
        self._test_label.setWordWrap(True)
        t_layout.addWidget(self._test_label, 1)
        root.addWidget(test_card)

        # 底部
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._btn_save = QPushButton("保存并启用此配置")
        self._btn_save.setObjectName("primary")
        self._btn_save.clicked.connect(self._on_save)
        bottom.addWidget(self._btn_save)
        root.addLayout(bottom)

    # ---------- 数据加载 ----------

    def load_from_config(self) -> None:
        cfg = self._controller.cfg
        api = cfg.asr.api

        self._radio_api.setChecked(cfg.asr.engine == "api")
        self._radio_local.setChecked(cfg.asr.engine != "api")

        self._edit_base_url.setText(api.base_url)
        self._edit_endpoint.setText(api.endpoint_path)
        self._edit_model.setText(api.model)
        self._spin_timeout.setValue(api.timeout_s)
        self._edit_text_path.setText(api.response_text_path)
        self._edit_headers.setPlainText(api.custom_headers_json)

        index = self._combo_template.findData(api.template)
        if index >= 0:
            self._combo_template.setCurrentIndex(index)

        if self._controller.secrets.has_api_key():
            self._edit_key.clear()
            self._edit_key.setPlaceholderText("已保存密钥（留空保持不变）")
        else:
            self._edit_key.setPlaceholderText("sk-…")
        self._edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._btn_show_key.setChecked(False)

        self._show_template_note(api.template)
        self._test_label.setText("未测试")
        self._test_label.setStyleSheet("color: #6e7781;")

    # ---------- 模板 ----------

    def _current_template(self) -> ApiTemplate | None:
        template_id = self._combo_template.currentData()
        for tpl in API_TEMPLATES:
            if tpl.id == template_id:
                return tpl
        return None

    def _show_template_note(self, template_id: str) -> None:
        tpl = None
        for item in API_TEMPLATES:
            if item.id == template_id:
                tpl = item
                break
        if tpl is None:
            self._template_note.setText("")
            return
        color = "#57606a" if tpl.supported else "#ca8a04"
        self._template_note.setText(tpl.note)
        self._template_note.setStyleSheet(f"color: {color};")

    def _on_apply_template(self) -> None:
        tpl = self._current_template()
        if tpl is None:
            return
        self._edit_base_url.setText(tpl.base_url)
        self._edit_model.setText(tpl.model)
        self._edit_endpoint.setText("/audio/transcriptions")
        self._edit_text_path.setText("text")
        self._edit_headers.setPlainText("")
        self._show_template_note(tpl.id)
        if not tpl.supported:
            self._controller.notify("该厂商使用私有协议，当前版本未实现专用适配器，配置可能无法工作")

    # ---------- 交互 ----------

    def _on_toggle_key(self, checked: bool) -> None:
        self._edit_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self._btn_show_key.setText("🙈 隐藏" if checked else "👁 显示")

    def _collect_api(self) -> ApiConfig:
        return ApiConfig(
            template=self._combo_template.currentData() or "custom",
            base_url=self._edit_base_url.text().strip(),
            endpoint_path=self._edit_endpoint.text().strip() or "/audio/transcriptions",
            model=self._edit_model.text().strip(),
            timeout_s=self._spin_timeout.value(),
            response_text_path=self._edit_text_path.text().strip() or "text",
            custom_headers_json=self._edit_headers.toPlainText().strip(),
        )

    def _effective_key(self) -> str:
        typed = self._edit_key.text().strip()
        if typed:
            return typed
        return self._controller.api_key() or ""

    def _on_test(self) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            return
        api = self._collect_api()
        try:
            config_module.validate_api(api)
        except config_module.ConfigError as exc:
            self._set_test_result(False, str(exc))
            return

        key = self._effective_key()
        if not key:
            self._set_test_result(False, "尚未填写 API 密钥，无法测试")
            return

        self._btn_test.setEnabled(False)
        self._test_label.setText("正在测试…")
        self._test_label.setStyleSheet("color: #6e7781;")

        asr_cfg = replace(self._controller.cfg.asr, engine="api", api=api)
        worker = ConnectionTestWorker(asr_cfg, key, parent=self)
        worker.finished_result.connect(self._on_test_done)
        self._test_worker = worker
        worker.start()

    def _on_test_done(self, result: ConnectionTestResult) -> None:
        self._btn_test.setEnabled(True)
        self._set_test_result(result.ok, result.message, result.kind)

    def _set_test_result(self, ok: bool, message: str, kind: str = "") -> None:
        if ok:
            color = "#2ea043"
            prefix = "🟢"
        elif kind in ("auth", "rate_limit", "empty"):
            color = "#ca8a04"
            prefix = "⚠️"
        else:
            color = "#cf222e"
            prefix = "🔴"
        self._test_label.setText(f"{prefix} {message}")
        self._test_label.setStyleSheet(f"color: {color};")

    # ---------- 保存 ----------

    def _on_save(self) -> None:
        if self._switch_worker is not None and self._switch_worker.isRunning():
            self._controller.notify("上一次切换还在进行中，请稍候")
            return

        api = self._collect_api()
        try:
            config_module.validate_api(api)
        except config_module.ConfigError as exc:
            self._controller.notify(f"配置有误：{exc}")
            return

        use_api = self._radio_api.isChecked()
        typed_key = self._edit_key.text().strip()
        if typed_key:
            self._controller.secrets.set_api_key(DEFAULT_PROFILE, typed_key)
            self._edit_key.clear()
            self._edit_key.setPlaceholderText("已保存密钥（留空保持不变）")

        if use_api and not self._effective_key():
            self._controller.notify("使用云端 API 前请先填写 API Key")
            return

        cfg = self._controller.cfg
        new_asr = replace(
            cfg.asr,
            engine="api" if use_api else "faster_whisper",
            api=api,
        )

        # 当前本地运行、且仍选本地：只更新 API 配置并保存，不重建本地引擎。
        if not use_api and cfg.asr.engine != "api":
            cfg.asr.api = api
            self._controller.save_config()
            self._controller.notify("API 配置已保存（当前仍使用本地模型）")
            return

        self._btn_save.setEnabled(False)
        worker = EngineSwitchWorker(
            self._controller, new_asr, self._controller.api_key(), parent=self
        )
        worker.finished_result.connect(self._on_save_done)
        self._switch_worker = worker
        worker.start()

    def _on_save_done(self, ok: bool, detail: str) -> None:
        self._btn_save.setEnabled(True)
        if ok:
            path = self._controller.save_config()
            self._controller.notify(
                f"已保存并启用：{detail}" + (f"（配置：{path}）" if path else "")
            )
            self.load_from_config()
        else:
            self._controller.notify(f"启用失败：{detail}")
