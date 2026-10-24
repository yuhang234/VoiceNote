"""应用装配：把采集 → 分段 → 识别 → 落盘串起来，并挂上界面。

线程模型（三段 + Qt 主线程）：

    音频回调线程   sounddevice 驱动触发，只做入队
    segment 线程   消费音频队列，跑 VAD 分段，产出语音段
    asr 线程       消费语音段，跑识别，写盘
    主线程         Qt 事件循环（QApplication），同时承载托盘、主窗口、设置页

选线程而不是多进程：模型只加载一次，ctranslate2 推理时会释放 GIL，
而 16GB 内存下多进程会各存一份模型（约 1.5GB），不划算。

界面（PySide6）只在 ``_init_ui`` 里延迟导入：核心的录音/分段/落盘逻辑
以及单元测试不依赖 Qt。托盘、窗口、设置页共享同一个 Qt 事件循环，
彻底消除旧版 pystray + 消息循环竞争的问题。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import config as config_module
from .asr import create_engine
from .asr.base import ASREngine
from .audio import AudioCapture
from .config import AsrConfig, Config
from .cuda_env import register_cuda_dlls
from .models import ensure_vad_model, model_cached
from .paths import open_in_default_app
from .secret_store import SecretStore
from .status import IconState
from .store import Store
from .vad import Segment, Segmenter, SileroVad

log = logging.getLogger(__name__)

# 队列深度都留得比较宽：宁可多缓冲几秒，也不要因为瞬时抖动丢用户的话。
AUDIO_QUEUE_MAX = 64  # 64 × 32ms ≈ 2 秒
SEGMENT_QUEUE_MAX = 8

JOIN_TIMEOUT_S = 30.0


class SingleInstanceError(Exception):
    """已经有实例在跑了。"""


class _InstanceLock:
    """文件锁，防止同时跑两个实例。

    两个实例会各开一路麦克风、各往同一天的 markdown 里追加，
    记录会重复而且很难察觉，所以必须挡住。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def acquire(self) -> None:
        import msvcrt

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a+")
        try:
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise SingleInstanceError(
                f"已经有一个 VoiceNote 在运行了（锁文件：{self._path}）"
            ) from exc

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception as exc:
            log.debug("释放锁失败：%s", exc)
        finally:
            self._fh.close()
            self._fh = None


class Application:
    """应用中枢：实现托盘/窗口所需的能力，并托管三条后台线程。"""

    def __init__(
        self,
        cfg: Config,
        *,
        config_path: Path | None = None,
        engine_factory: Callable[..., ASREngine] | None = None,
        secrets: SecretStore | None = None,
    ) -> None:
        self._cfg = cfg
        self._config_path = Path(config_path) if config_path is not None else None
        self._engine_factory = engine_factory or create_engine
        self._secrets = secrets or SecretStore(cfg.state_dir)

        self._lock = _InstanceLock(cfg.state_dir / "session.lock")
        self._paused = threading.Event()
        self._stopping = threading.Event()
        self._shutdown_done = threading.Event()
        self._engine_ready = threading.Event()
        self._asr_lock = threading.Lock()
        # 引擎代号：加载与手动热切换竞争时，以代号小者为准丢弃过期结果。
        self._engine_epoch = 0

        self._audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=AUDIO_QUEUE_MAX)
        self._segment_q: queue.Queue[Segment] = queue.Queue(maxsize=SEGMENT_QUEUE_MAX)

        self._audio: AudioCapture | None = None
        self._segmenter: Segmenter | None = None
        self._engine: ASREngine | None = None
        self._store: Store | None = None
        self._threads: list[threading.Thread] = []
        self._asr_thread: threading.Thread | None = None

        # Qt 相关（没有界面时保持为 None，核心逻辑照常可测）
        self._qt_app: Any = None
        self._window: Any = None
        self._tray: Any = None
        self._bridge: Any = None
        self._state = IconState.LISTENING

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动全部组件，然后阻塞在 Qt 事件循环里，直到 shutdown()。"""
        self._lock.acquire()

        # 必须在任何 ctranslate2 调用之前注册 DLL 目录。
        register_cuda_dlls()

        vad_path = ensure_vad_model(self._cfg.models_dir)
        self._store = Store(self._cfg)
        self._segmenter = Segmenter(
            SileroVad(vad_path), self._cfg.vad, self._cfg.audio.sample_rate
        )
        self._audio = AudioCapture(self._cfg.audio, self._audio_q)

        # 界面必须早于模型加载建好。模型加载（首次运行还要下 1.6GB）放在 asr
        # 线程里，托盘才能立刻可见并弹出下载提示 —— 否则无控制台的打包版就是
        # 一个十几分钟毫无反应的进程，用户只会以为程序坏了。
        try:
            if not self._init_ui():
                self._teardown_ui()
                self._lock.release()
                raise RuntimeError(
                    "界面依赖不可用：请先安装 PySide6（pip install PySide6-Essentials）"
                )
        except Exception:
            self._teardown_ui()
            self._lock.release()
            raise

        self._threads = [
            threading.Thread(target=self._segment_loop, name="segment", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._ensure_asr_thread()

        self._audio.start()
        log.info("VoiceNote 已启动，正在准备识别模型…（托盘图标：黄=准备中，绿=监听中）")

        assert self._qt_app is not None
        self._qt_app.exec()  # 阻塞，直到托盘「退出」或关闭行为为 exit 时关闭窗口

        # Qt 循环结束了。shutdown() 可能是托盘菜单在主线程里调用的，
        # 那里的收尾工作还要把最后一段话 flush 完 —— 直接返回会让进程退出、
        # 把用户最后说的话截掉，所以这里必须等它收完尾。
        self.shutdown()
        self._shutdown_done.wait(timeout=JOIN_TIMEOUT_S)

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        log.info("正在退出…")

        # 顺序很重要：先停采集（不再产生新音频），再把半段交出去，
        # 最后才放 worker 退出 —— 反过来的话最后一段话会被丢掉。
        if self._audio is not None:
            self._audio.stop()

        if self._segmenter is not None:
            try:
                tail = self._segmenter.flush()
                if tail is not None:
                    self._enqueue_segment(tail)
            except Exception:
                log.exception("收尾时处理最后一段失败")

        self._stopping.set()

        for thread in self._threads:
            thread.join(timeout=JOIN_TIMEOUT_S)

        self._teardown_ui()
        self._lock.release()
        self._shutdown_done.set()
        log.info("已退出")

    # ---------- 界面 ----------

    def _init_ui(self) -> bool:
        try:
            from .ui.app_window import MainWindow, ensure_qt_app
            from .ui.bridge import UiBridge
            from .ui.tray_icon import TrayIcon
        except ImportError:
            log.exception("无法加载界面依赖（PySide6），VoiceNote 需要图形界面才能运行")
            return False

        try:
            self._qt_app = ensure_qt_app()
            self._window = MainWindow(self)
            self._tray = TrayIcon(self)
            self._bridge = UiBridge()

            # 信号连接：worker 线程 emit → 自动排队到主线程执行。
            self._bridge.state_changed.connect(self._tray.set_state)
            self._bridge.state_changed.connect(self._window.on_state_changed)
            self._bridge.message.connect(self._tray.notify)
            self._bridge.message.connect(self._window.on_notification)
            self._bridge.transcript_saved.connect(self._window.on_transcript_saved)

            self._window.attach_tray(self._tray)
            self._tray.show()
        except Exception as exc:
            log.exception("界面初始化失败")
            raise RuntimeError(f"界面初始化失败：{exc}") from exc

        if self._cfg.general.open_ui_on_startup:
            self._window.show()
        return True

    def _teardown_ui(self) -> None:
        for widget in (self._window, self._tray):
            if widget is not None:
                try:
                    widget.hide()
                except Exception as exc:
                    log.debug("隐藏界面组件失败：%s", exc)
        if self._qt_app is not None:
            try:
                self._qt_app.quit()
            except Exception as exc:
                log.debug("退出 Qt 事件循环失败：%s", exc)

    def show_page(self, page: str) -> None:
        """由托盘/窗口请求：显示主窗口并切换到指定页面。"""
        if self._window is None:
            return
        self._window.show_page(page)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def notify(self, message: str) -> None:
        """弹一条托盘气泡（从任意线程调用都安全）。"""
        if self._bridge is not None:
            self._bridge.message.emit(message)
        else:
            log.info("%s", message)

    # ---------- 托盘/界面控制器协议 ----------

    @property
    def cfg(self) -> Config:
        return self._cfg

    @property
    def secrets(self) -> SecretStore:
        return self._secrets

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def state(self) -> IconState:
        return self._state

    @property
    def active_engine_name(self) -> str:
        if self._engine is not None:
            return getattr(self._engine, "name", str(self._engine))
        if self._cfg.asr.engine == "api":
            return f"api/{self._cfg.asr.api.model}"
        return f"faster-whisper/{self._cfg.asr.model}"

    def api_key(self) -> str | None:
        """当前生效的 API Key（仅存在于内存和 secrets.json）。"""
        return self._secrets.get_api_key()

    def pause(self) -> None:
        if self.paused:
            return
        self._paused.set()
        if self._audio is not None:
            self._audio.stop()  # 真把麦克风关掉，而不是只忽略数据
        log.info("已暂停监听")
        self._set_state(IconState.PAUSED)

    def resume(self) -> None:
        if not self.paused:
            return
        self._paused.clear()

        # 丢掉暂停期间可能残留的音频，并清空分段器，
        # 否则恢复后第一段会带上暂停前的内容。
        self._drain(self._audio_q)
        if self._segmenter is not None:
            self._segmenter.reset()

        if self._audio is not None:
            try:
                self._audio.restart()
            except Exception:
                log.exception("恢复采集失败，可能需要重启程序")
                self._set_state(IconState.ERROR)
                return

        log.info("已恢复监听")
        self._set_state(IconState.LISTENING)

    def open_today(self) -> None:
        """打开主界面的「日常记录」页（软件内阅读，不再拉起外部编辑器）。"""
        self.show_page("transcripts")

    def open_data_dir(self) -> None:
        try:
            self._cfg.data_dir.mkdir(parents=True, exist_ok=True)
            self.open_path(self._cfg.data_dir)
        except Exception:
            log.exception("打开数据目录失败：%s", self._cfg.data_dir)
            self.notify(f"无法打开数据目录：{self._cfg.data_dir}")

    def open_path(self, path: Path) -> None:
        try:
            open_in_default_app(Path(path))
        except Exception as exc:
            log.exception("用系统默认程序打开失败：%s", path)
            self.notify(f"无法打开：{path}（{exc}）")

    # ---------- 配置与引擎热切换 ----------

    def save_config(self) -> Path | None:
        """把当前配置写回 config.toml。返回写入路径；失败返回 None。"""
        path = self._config_path or config_module.default_config_path()
        try:
            config_module.save(self._cfg, path)
            log.info("配置已保存：%s", path)
            return path
        except OSError as exc:
            log.exception("配置写入失败：%s", path)
            self.notify(f"配置写入失败：{exc}")
            return None

    def switch_engine(self, new_asr_cfg: AsrConfig, api_key: str | None = None) -> bool:
        """由设置界面触发的热切换。线程安全，不丢录音。

        创建与预热都在 ``_asr_lock`` 内完成：换引擎和推理共用同一把锁，
        保证旧引擎不会在推理进行中被释放；失败时旧引擎原样保留。
        """
        key = api_key if api_key is not None else self.api_key()
        with self._asr_lock:
            try:
                old_engine = self._engine
                # 1. 创建并预热新引擎（失败时旧引擎原样保留）
                new_engine = self._engine_factory(new_asr_cfg, api_key=key)
                new_engine.warmup()
                # 2. 原子替换
                self._engine_epoch += 1
                self._engine = new_engine
                self._engine_ready.set()
                self._cfg.asr = new_asr_cfg
            except Exception:
                log.exception("ASR 引擎热切换失败，继续使用原引擎")
                self._set_state(IconState.ERROR)
                return False

        # 3. 释放旧引擎资源（如 CTranslate2 的 GPU 显存）。
        # 此时锁已释放，但由于所有推理都在锁内取引擎，不会有人还在用它。
        del old_engine
        log.info("ASR 引擎已成功热切换至：%s", self.active_engine_name)
        self._ensure_asr_thread()
        self._set_state(IconState.PAUSED if self.paused else IconState.LISTENING)
        return True

    # ---------- worker 线程 ----------

    def _ensure_asr_thread(self) -> None:
        """确保 asr 线程在跑。

        首次加载失败或加载期被手动切换时线程可能已退出；热切换成功后需要
        把它重新拉起来，否则新引擎没有消费者。
        """
        if self._asr_thread is not None and self._asr_thread.is_alive():
            return
        thread = threading.Thread(target=self._asr_loop, name="asr", daemon=True)
        self._asr_thread = thread
        self._threads.append(thread)
        thread.start()

    def _segment_loop(self) -> None:
        assert self._segmenter is not None
        while not self._stopping.is_set():
            try:
                chunk = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                for segment in self._segmenter.push(chunk):
                    if self._engine_ready.is_set():
                        self._enqueue_segment(segment)
                    else:
                        # 引擎还在加载（首次运行要下模型）。这时说的话没法识别，
                        # 与其塞满队列、等模型好了再补识别一堆十几分钟前的过期内容，
                        # 不如直接丢掉。
                        log.debug(
                            "识别引擎尚未就绪，丢弃一段 %.1fs", segment.duration_s
                        )
            except Exception:
                log.exception("分段出错，跳过这一块音频")

    def _asr_loop(self) -> None:
        if not self._engine_ready.is_set() and not self._load_engine():
            return

        while True:
            # 退出时把队列里剩下的段处理完再走，别丢用户最后几句话。
            if self._stopping.is_set() and self._segment_q.empty():
                return
            try:
                segment = self._segment_q.get(timeout=0.2)
            except queue.Empty:
                continue
            self._transcribe(segment)

    def _load_engine(self) -> bool:
        """加载识别模型（首次运行会先下载约 1.6GB）。失败返回 False。

        放在 asr 线程里而不是 start()：托盘这时已经在跑了，下载提示才弹得出来。
        """
        cfg = self._cfg.asr
        epoch = self._engine_epoch
        first_run = cfg.engine in ("faster_whisper", "parakeet") and not model_cached(
            cfg.model
        )
        if first_run:
            source = self._cfg.general.hf_endpoint or "huggingface.co"
            log.info(
                "本地没有 %s 的缓存，开始下载（约 1.6GB，来源 %s）",
                cfg.model,
                source,
            )
            self.notify(
                f"首次运行，正在下载识别模型（约 1.6GB）\n"
                f"来源：{source}\n下载期间无法记录，请稍候…"
            )
            self._set_state(IconState.LOADING)

        try:
            t0 = time.perf_counter()
            engine = self._engine_factory(cfg, api_key=self.api_key())
            log.info("模型加载完成，用时 %.1fs", time.perf_counter() - t0)
        except Exception:
            log.exception("ASR 引擎加载失败，本次运行无法识别")
            self._set_state(IconState.ERROR)
            return False

        try:
            t0 = time.perf_counter()
            engine.warmup()
            log.info("模型预热完成，用时 %.1fs", time.perf_counter() - t0)
        except Exception:
            # 预热失败只是慢，不该拦住整个应用。
            log.exception("模型预热失败，首次识别会明显变慢")

        with self._asr_lock:
            if epoch != self._engine_epoch:
                # 用户在加载期间已经手动切换了引擎：丢弃这次加载的结果，
                # 继续消费队列（新引擎已就绪）。
                log.info("模型加载期间引擎已被手动切换，丢弃本次加载结果")
                return True
            self._engine = engine
            self._engine_ready.set()

        if first_run:
            self.notify("模型准备完成，已开始监听")
        self._set_state(IconState.PAUSED if self.paused else IconState.LISTENING)
        return True

    def _transcribe(self, segment: Segment) -> None:
        store = self._store
        if store is None:
            return

        self._set_state(IconState.TRANSCRIBING)
        t0 = time.perf_counter()
        try:
            # ctranslate2 的 WhisperModel 不支持并发调用同一个实例；
            # 引擎对象的读取与推理都放在同一把锁里，热切换才不会把正在
            # 使用的引擎释放掉。
            with self._asr_lock:
                engine = self._engine
                if engine is None:
                    return
                text = engine.transcribe(segment.audio, segment.sample_rate)
        except Exception:
            log.exception("识别失败（段长 %.1fs）", segment.duration_s)
            return
        finally:
            self._set_state(
                IconState.PAUSED if self.paused else IconState.LISTENING
            )

        elapsed = time.perf_counter() - t0
        if not text:
            log.debug("识别结果为空（段长 %.1fs，耗时 %.1fs）", segment.duration_s, elapsed)
            return

        store.save(segment, text)
        log.info("[%.0fms] %s", elapsed * 1000, text)
        self._signal_transcript_saved(segment)

    # ---------- 辅助 ----------

    def _enqueue_segment(self, segment: Segment) -> None:
        log.info("切出一段：%.1fs", segment.duration_s)
        try:
            self._segment_q.put(segment, timeout=1.0)
        except queue.Full:
            log.warning("识别队列已满，丢弃这一段（%.1fs）", segment.duration_s)

    def _set_state(self, state: IconState) -> None:
        self._state = state
        if self._bridge is not None:
            try:
                self._bridge.state_changed.emit(state)
            except RuntimeError:
                pass

    def _signal_transcript_saved(self, segment: Segment) -> None:
        if self._bridge is None:
            return
        day = segment.started_at.strftime("%Y-%m-%d")
        path = self._cfg.transcripts_dir / f"{day}.md"
        try:
            self._bridge.transcript_saved.emit(str(path))
        except RuntimeError:
            pass

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return


def run(cfg: Config, config_path: Path | None = None) -> int:
    app = Application(cfg, config_path=config_path)
    try:
        app.start()
    except SingleInstanceError as exc:
        log.error("%s", exc)
        return 3
    except KeyboardInterrupt:
        app.shutdown()
        return 0
    except Exception:
        log.exception("启动失败")
        return 1
    return 0
