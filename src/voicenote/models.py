"""模型文件的下载与定位。

VAD 模型我们自己在本地准备；Whisper 权重交给 faster-whisper 从 HuggingFace
拉取并缓存，这里负责三件事：

1. 本地模型清单（tiny / base / small / large-v3-turbo，以及明确标注不可用的 SenseVoice）；
2. 判断某个模型的权重是否已经在缓存里（下拉框和托盘提示都要用）；
3. 基础下载能力 ``download_model`` —— 走 huggingface_hub 的官方快照下载，
   天然带断点续传（``.incomplete`` 文件）与重试；下载失败由调用方（设置界面）
   提供"[重试]"按钮。

下载函数把"怎么下"抽象成可注入的 ``fetch``，单元测试里注入假实现即可，
不需要联网也不需要装 huggingface_hub 之外的任何东西。
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

VAD_MODEL_FILENAME = "silero_vad.onnx"
VAD_MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/"
    "src/silero_vad/data/silero_vad.onnx"
)

_WEIGHT_SUFFIXES = {".bin", ".safetensors", ".npz"}
_HF_ALLOW_PATTERNS = ["*.bin", "*.safetensors", "*.npz", "*.json", "*.txt", "*.model"]


class ModelDownloadError(RuntimeError):
    """下载失败（网络、磁盘、校验等）。"""


class ModelUnavailableError(ModelDownloadError):
    """这个模型在当前版本上不可用（例如 SenseVoice 需要未实现的 ONNX 引擎）。"""


class DownloadCancelled(ModelDownloadError):
    """用户主动取消了下载。"""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """一个本地 ASR 模型的静态描述（界面直接展示它）。"""

    id: str
    repo: str
    label: str
    size_mb: int
    params_m: int
    speed_hint: str
    description: str
    license: str = "MIT"
    available: bool = True
    unavailable_reason: str = ""


#: 界面模型卡片的数据源。顺序 = 展示顺序（高精度在前，轻量在后）。
LOCAL_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="large-v3-turbo",
        repo="Systran/faster-whisper-large-v3-turbo",
        label="高精度主力",
        size_mb=1630,
        params_m=809,
        speed_hint="GPU RTF ~0.05 / CPU 较慢",
        description="有 NVIDIA 显卡时的默认选择，中文专有名词与中英混说最准。",
    ),
    ModelSpec(
        id="small",
        repo="Systran/faster-whisper-small",
        label="平衡推荐",
        size_mb=484,
        params_m=244,
        speed_hint="CPU RTF ~0.5",
        description="中文识别达到实用标准，无独显的办公机主力。",
    ),
    ModelSpec(
        id="base",
        repo="Systran/faster-whisper-base",
        label="极速轻量",
        size_mb=145,
        params_m=74,
        speed_hint="CPU RTF ~0.2",
        description="比 tiny 明显更好的断句，体积依然很小。",
    ),
    ModelSpec(
        id="tiny",
        repo="Systran/faster-whisper-tiny",
        label="超轻低配",
        size_mb=75,
        params_m=39,
        speed_hint="CPU RTF < 0.1",
        description="老旧笔记本首选，启动瞬时、内存占用最低。",
    ),
    ModelSpec(
        id="sensevoice-small",
        repo="FunAudioLLM/SenseVoiceSmall",
        label="中文特化（实验性）",
        size_mb=220,
        params_m=234,
        speed_hint="ONNX CPU 极快（引擎未实现）",
        description="阿里达摩院开源的中文语音大模型；需要专用 ONNX 推理适配器。",
        available=False,
        unavailable_reason=(
            "SenseVoice 的 ONNX 推理适配器尚未实现（规划在 Phase 3），"
            "当前版本无法加载该模型。"
        ),
    ),
)

MODEL_IDS: tuple[str, ...] = tuple(spec.id for spec in LOCAL_MODELS)


def model_spec(model_id: str) -> ModelSpec | None:
    for spec in LOCAL_MODELS:
        if spec.id == model_id:
            return spec
    return None


def resolve_repo(model_id: str) -> str:
    """模型 id → HuggingFace 仓库名。

    优先用 faster-whisper 自带的映射表（保证和它实际加载的是同一个仓库），
    查不到再退回我们清单里的 repo。
    """
    try:
        from faster_whisper.utils import _MODELS

        repo = _MODELS.get(model_id)
        if repo:
            return repo
    except Exception as exc:
        log.debug("无法读取 faster-whisper 模型映射：%s", exc)
    spec = model_spec(model_id)
    return spec.repo if spec else model_id


def hf_hub_cache_dir() -> Path:
    """huggingface_hub 的模型缓存根目录。"""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        return Path(HF_HUB_CACHE)
    except Exception:
        hf_home = os.environ.get("HF_HOME")
        base = Path(hf_home) if hf_home else Path.home() / ".cache" / "huggingface"
        return base / "hub"


def model_cache_dir(model_id: str, hub_cache: Path | None = None) -> Path:
    repo = resolve_repo(model_id)
    root = Path(hub_cache) if hub_cache is not None else hf_hub_cache_dir()
    return root / f"models--{repo.replace('/', '--')}"


def whisper_model_cached(model: str, hub_cache: Path | None = None) -> bool:
    """判断 faster-whisper 的权重是否已经缓存在本地。

    打包版第一次启动要下约 1.6GB，得先知道该不该提示用户"正在下载" ——
    否则一个无控制台的图标静静卡十几分钟，用户只会以为程序坏了。

    判断不出来时返回 False（当作没缓存）。最坏后果只是多弹一次提示，
    比"该提示时没提示"要好。
    """
    try:
        snapshots = model_cache_dir(model, hub_cache) / "snapshots"
        if not snapshots.is_dir():
            return False

        for snap in snapshots.iterdir():
            if not snap.is_dir():
                continue
            if any(
                f.is_file() and f.suffix in _WEIGHT_SUFFIXES for f in snap.iterdir()
            ):
                return True
        return False
    except Exception as exc:
        log.debug("无法判断模型缓存状态：%s", exc)
        return False


def model_downloaded_size(model_id: str, hub_cache: Path | None = None) -> int:
    """已缓存权重的字节数（用于界面展示"已就绪"时的实际占盘）。"""
    root = model_cache_dir(model_id, hub_cache)
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def delete_model_cache(model_id: str, hub_cache: Path | None = None) -> bool:
    """删除一个模型的缓存目录。返回是否真的删掉了东西。

    调用方（界面）负责保证"当前生效的模型不允许删除"。
    """
    root = model_cache_dir(model_id, hub_cache)
    if not root.is_dir():
        return False
    shutil.rmtree(root)
    log.info("已删除模型缓存：%s", root)
    return True


@dataclass(slots=True)
class DownloadProgress:
    """下载进度快照。``total_bytes == 0`` 表示总大小未知（不确定进度）。"""

    model_id: str
    fraction: float
    downloaded_bytes: int
    total_bytes: int
    speed_bps: float
    note: str = ""

    @property
    def speed_mb_s(self) -> float:
        return self.speed_bps / 1e6


ProgressCallback = Callable[[DownloadProgress], None]
FetchFunc = Callable[
    [ModelSpec, Path, threading.Event | None, ProgressCallback | None],
    Path,
]


def _hf_snapshot_fetch(
    spec: ModelSpec,
    hub_cache: Path,
    cancel: threading.Event | None,
    progress: ProgressCallback | None,
) -> Path:
    """默认下载实现：huggingface_hub 快照下载（带断点续传）。"""
    from huggingface_hub import snapshot_download

    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("下载已取消")

    endpoint = os.environ.get("HF_ENDPOINT") or None
    tqdm_class = _make_tqdm_class(spec.id, progress)

    kwargs: dict = {
        "repo_id": spec.repo,
        "allow_patterns": _HF_ALLOW_PATTERNS,
        "max_workers": 4,
    }
    if endpoint:
        kwargs["endpoint"] = endpoint
    if tqdm_class is not None:
        kwargs["tqdm_class"] = tqdm_class

    if progress is not None:
        progress(
            DownloadProgress(spec.id, 0.0, 0, spec.size_mb * 1024 * 1024, 0.0, "开始下载")
        )

    if cancel is not None:
        raise DownloadCancelled("下载已取消")

    path = Path(snapshot_download(**kwargs))

    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("下载已取消")
    if progress is not None:
        progress(
            DownloadProgress(spec.id, 1.0, model_downloaded_size(spec.id, hub_cache), 0, 0.0, "完成")
        )
    return path


def _make_tqdm_class(model_id: str, progress: ProgressCallback | None):
    """把 tqdm 的进度回调转成 DownloadProgress；tqdm 不可用时返回 None。"""
    if progress is None:
        return None
    try:
        from tqdm import tqdm as _tqdm
    except Exception:
        return None

    class _ProgressTqdm(_tqdm):
        def update(self, n=1):  # type: ignore[override]
            result = super().update(n)
            try:
                total = float(self.total or 0)
                done = float(self.n or 0)
                progress(
                    DownloadProgress(
                        model_id,
                        (done / total) if total else 0.0,
                        int(done),
                        int(total),
                        float(getattr(self, "rate", 0.0) or 0.0),
                    )
                )
            except Exception:
                pass
            return result

    return _ProgressTqdm


def download_model(
    model_id: str,
    *,
    hf_endpoint: str = "",
    hub_cache: Path | None = None,
    cancel: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    fetch: FetchFunc | None = None,
    retries: int = 2,
    retry_delay_s: float = 1.0,
) -> Path:
    """确保模型权重在本地缓存里，返回缓存目录。

    - ``hf_endpoint`` 非空时覆盖 HF_ENDPOINT（只影响本次下载的进程环境）；
    - ``fetch`` 可注入，便于测试与将来替换下载后端；
    - ``retries`` 是基础重试：网络抖动导致的失败自动重试，取消不重试。
    """
    spec = model_spec(model_id)
    if spec is not None and not spec.available:
        raise ModelUnavailableError(spec.unavailable_reason or f"{model_id} 当前不可用")

    cache_root = Path(hub_cache) if hub_cache is not None else hf_hub_cache_dir()

    if whisper_model_cached(model_id, cache_root):
        return model_cache_dir(model_id, cache_root)

    if hf_endpoint:
        # huggingface_hub 的常量在 import 时就固化，覆盖环境变量让它生效。
        os.environ["HF_ENDPOINT"] = hf_endpoint

    fetch_fn = fetch or _hf_snapshot_fetch
    target_spec = spec or ModelSpec(
        id=model_id,
        repo=resolve_repo(model_id),
        label=model_id,
        size_mb=0,
        params_m=0,
        speed_hint="",
        description="",
    )

    last_exc: Exception | None = None
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled("下载已取消")
        try:
            fetch_fn(target_spec, cache_root, cancel, progress)
            if not whisper_model_cached(model_id, cache_root):
                raise ModelDownloadError(
                    "下载流程结束，但缓存里仍找不到权重文件，请重试或检查下载源"
                )
            return model_cache_dir(model_id, cache_root)
        except DownloadCancelled:
            raise
        except Exception as exc:
            last_exc = exc
            log.warning(
                "模型 %s 下载失败（第 %d/%d 次）：%s", model_id, attempt, attempts, exc
            )
            if attempt < attempts:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled("下载已取消") from exc
                time.sleep(retry_delay_s)
    raise ModelDownloadError(
        f"下载 {model_id} 失败：{last_exc}"
    ) from last_exc


def ensure_vad_model(models_dir: Path) -> Path:
    """返回 VAD 模型路径，不存在则下载。"""
    target = models_dir / VAD_MODEL_FILENAME
    if target.is_file() and target.stat().st_size > 0:
        return target

    models_dir.mkdir(parents=True, exist_ok=True)
    log.info("下载 VAD 模型：%s", VAD_MODEL_URL)

    # 先下到临时文件再改名，避免下载中断留下半个文件被当成可用模型。
    tmp = target.with_suffix(".onnx.part")
    try:
        with urllib.request.urlopen(VAD_MODEL_URL, timeout=60) as resp:
            tmp.write_bytes(resp.read())
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    log.info("VAD 模型就绪：%s（%.1f MB）", target, target.stat().st_size / 1e6)
    return target
