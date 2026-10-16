"""设置界面用的后台工作线程。

下载、热切换、连通性测试都会阻塞若干秒，必须放到 QThread 里，
否则界面会假死。结果一律通过信号回到主线程。
"""

from __future__ import annotations

import threading
import logging

from PySide6.QtCore import QThread, Signal

from ..asr.openai_api_engine import ConnectionTestResult, test_connection
from ..config import AsrConfig
from ..models import (
    DownloadCancelled,
    DownloadProgress,
    download_model,
)

log = logging.getLogger(__name__)


class ModelDownloadWorker(QThread):
    """按设计稿契约实现：progress_changed(model, percent, speed_mb_s)。"""

    progress_changed = Signal(str, float, float)
    download_finished = Signal(str, bool, str)

    def __init__(self, model_id: str, hf_endpoint: str = "", parent=None) -> None:
        super().__init__(parent)
        self._model_id = model_id
        self._hf_endpoint = hf_endpoint
        self._cancel = threading.Event()

    @property
    def model_id(self) -> str:
        return self._model_id

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D102 - QThread 入口
        def on_progress(progress: DownloadProgress) -> None:
            self.progress_changed.emit(
                progress.model_id, progress.fraction * 100.0, progress.speed_mb_s
            )

        try:
            path = download_model(
                self._model_id,
                hf_endpoint=self._hf_endpoint,
                cancel=self._cancel,
                progress=on_progress,
            )
        except DownloadCancelled:
            self.download_finished.emit(self._model_id, False, "下载已取消")
        except Exception as exc:
            log.exception("模型下载失败：%s", self._model_id)
            self.download_finished.emit(self._model_id, False, str(exc))
        else:
            self.download_finished.emit(self._model_id, True, str(path))


class EngineSwitchWorker(QThread):
    """在后台线程里执行 ASR 热切换（Application.switch_engine 是线程安全的）。"""

    finished_result = Signal(bool, str)

    def __init__(self, controller, asr_cfg: AsrConfig, api_key: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._cfg = asr_cfg
        self._api_key = api_key

    def run(self) -> None:  # noqa: D102
        try:
            ok = self._controller.switch_engine(self._cfg, self._api_key)
        except Exception as exc:
            log.exception("引擎切换线程异常")
            self.finished_result.emit(False, str(exc))
            return
        if ok:
            self.finished_result.emit(True, self._controller.active_engine_name)
        else:
            self.finished_result.emit(False, "切换失败（详见日志），仍继续使用原引擎")


class ConnectionTestWorker(QThread):
    """调用云端 API 做一次连通性测试。"""

    finished_result = Signal(object)

    def __init__(self, asr_cfg: AsrConfig, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self._cfg = asr_cfg
        self._api_key = api_key

    def run(self) -> None:  # noqa: D102
        try:
            result: ConnectionTestResult = test_connection(self._cfg, self._api_key)
        except Exception as exc:
            log.exception("连通性测试异常")
            result = ConnectionTestResult(False, "connection", f"测试失败：{exc}", 0)
        self.finished_result.emit(result)
