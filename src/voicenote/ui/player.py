"""轻量内嵌音频播放器。

复用项目已有的 soundfile（解码）+ sounddevice（输出），不引入 QtMultimedia
（那会把 PySide6-Addons 的 ~100MB 带进安装包，设计稿明确要避免）。

播放跑在独立线程里；播放/暂停/停止/拖动进度都是线程安全的。
没有可用音频设备（如无头 CI）时通过 ``failed`` 信号报告，不抛异常。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

_BLOCK_FRAMES = 2048


class AudioPlayer(QObject):
    """单文件播放器：同一时刻只放一个文件，播新的自动停旧的。"""

    position_changed = Signal(int, int)  # 当前毫秒, 总毫秒
    state_changed = Signal(str)  # playing | paused | stopped | finished
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._seek_lock = threading.Lock()
        self._pending_seek_ms: int | None = None
        self._active = False
        self._path: Path | None = None
        self._total_ms = 0

    @property
    def current_path(self) -> Path | None:
        return self._path

    @property
    def is_active(self) -> bool:
        return self._active

    # ---------- 控制 ----------

    def play(self, path: Path) -> None:
        self.stop()
        target = Path(path)
        if not target.is_file():
            self.failed.emit(f"音频文件不存在：{target}")
            return

        self._path = target
        self._stop.clear()
        self._pause.clear()
        self._pending_seek_ms = None
        self._active = True
        self._thread = threading.Thread(
            target=self._run, args=(target,), name="audio-player", daemon=True
        )
        self._thread.start()

    def toggle_pause(self) -> None:
        if not self._active:
            return
        if self._pause.is_set():
            self._pause.clear()
            self.state_changed.emit("playing")
        else:
            self._pause.set()
            self.state_changed.emit("paused")

    def seek(self, position_ms: int) -> None:
        with self._seek_lock:
            self._pending_seek_ms = max(0, int(position_ms))

    def stop(self) -> None:
        thread = self._thread
        self._stop.set()
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)
        self._thread = None
        if self._active:
            self._finish("stopped")

    # ---------- 播放线程 ----------

    def _take_seek(self) -> int | None:
        with self._seek_lock:
            value = self._pending_seek_ms
            self._pending_seek_ms = None
            return value

    def _run(self, path: Path) -> None:
        try:
            import soundfile as sf

            data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:
            log.warning("读取音频失败 %s：%s", path, exc)
            self._active = False
            self.failed.emit(f"无法读取音频：{exc}")
            self.state_changed.emit("stopped")
            return

        if data.shape[0] == 0:
            self._active = False
            self.failed.emit("音频文件为空")
            self.state_changed.emit("stopped")
            return

        try:
            import sounddevice as sd

            stream = sd.OutputStream(
                samplerate=rate, channels=data.shape[1], dtype="float32"
            )
            stream.start()
        except Exception as exc:
            log.warning("打开音频输出失败：%s", exc)
            self._active = False
            self.failed.emit(f"无法打开音频输出设备：{exc}")
            self.state_changed.emit("stopped")
            return

        frames = data.shape[0]
        total_ms = int(frames * 1000 / rate)
        self._total_ms = total_ms
        position = 0
        self.state_changed.emit("playing")
        self.position_changed.emit(0, total_ms)

        try:
            while position < frames and not self._stop.is_set():
                seek_ms = self._take_seek()
                if seek_ms is not None:
                    position = max(0, min(frames, int(seek_ms * rate / 1000)))
                    self.position_changed.emit(int(position * 1000 / rate), total_ms)
                    continue

                if self._pause.is_set():
                    time.sleep(0.05)
                    continue

                chunk = data[position : position + _BLOCK_FRAMES]
                if chunk.shape[0] == 0:
                    break
                stream.write(chunk)
                position += chunk.shape[0]
                self.position_changed.emit(int(position * 1000 / rate), total_ms)
        except Exception as exc:
            log.warning("播放失败：%s", exc)
            self.failed.emit(f"播放失败：{exc}")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        finished = position >= frames and not self._stop.is_set()
        if self._active:
            self._finish("finished" if finished else "stopped")

    def _finish(self, state: str) -> None:
        self._active = False
        self.state_changed.emit(state)
