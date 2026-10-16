"""OpenAI 兼容的云端 ASR 引擎。

覆盖 OpenAI 官方、硅基流动 (SiliconFlow)、Groq Audio 以及任何遵守
``POST {base_url}/audio/transcriptions`` + ``multipart/form-data`` + ``{"text": ...}``
规范的网关（LocalAI、vLLM 等）。

协议依据（厂商官方文档核实，见设计报告 §8.1）：

- OpenAI:  https://platform.openai.com/docs/api-reference/audio
- SiliconFlow: https://docs.siliconflow.cn/cn/api-reference/audio/create-transcription
- Groq: https://console.groq.com/docs/speech-text

DashScope（阿里云百炼）等使用私有异步协议的厂商**不在**本适配器范围内，
模板里会明确标注不可用，而不是伪造支持。

错误分类（``AsrApiError.kind``）与界面提示的对应关系见报告 §8.3。
"""

from __future__ import annotations

import io
import json
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..config import ApiConfig, AsrConfig
from ..paths import bundle_root, project_root
from .base import SAMPLE_RATE

log = logging.getLogger(__name__)

#: 自定义请求头里代表真实密钥的占位符。
API_KEY_PLACEHOLDER = "{API_KEY}"

#: 连通性测试使用的样例音频文件名（打包资源与仓库里同一份）。
SAMPLE_FILENAME = "selftest_sample.flac"


class AsrApiError(RuntimeError):
    """云端 ASR 调用失败。

    kind 取值：auth / rate_limit / timeout / connection / http / parse / empty。
    """

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass(frozen=True, slots=True)
class ApiTemplate:
    """厂商模板：一键填充表单的静态数据。"""

    id: str
    label: str
    base_url: str
    model: str
    note: str
    supported: bool = True


API_TEMPLATES: tuple[ApiTemplate, ...] = (
    ApiTemplate(
        id="siliconflow",
        label="硅基流动 (SiliconFlow)",
        base_url="https://api.siliconflow.cn/v1",
        model="FunAudioLLM/SenseVoiceSmall",
        note="国内直连，性价比高；完全兼容 OpenAI 音频转写协议。",
    ),
    ApiTemplate(
        id="groq",
        label="Groq Audio (超高速)",
        base_url="https://api.groq.com/openai/v1",
        model="whisper-large-v3-turbo",
        note="全球推理速度最快；完全兼容 OpenAI 音频转写协议。",
    ),
    ApiTemplate(
        id="openai",
        label="OpenAI 官方",
        base_url="https://api.openai.com/v1",
        model="whisper-1",
        note="标准协议基线，国内访问需要自备网络条件。",
    ),
    ApiTemplate(
        id="dashscope",
        label="阿里云百炼 (DashScope)",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        model="sensevoice-v1",
        note=(
            "DashScope 使用私有异步协议（任务提交 + 外链音频，响应路径为 "
            "output.sentence[*].text），当前版本未实现专用适配器，暂不可用。"
        ),
        supported=False,
    ),
)


def template_by_id(template_id: str) -> ApiTemplate | None:
    for tpl in API_TEMPLATES:
        if tpl.id == template_id:
            return tpl
    return None


# ---------------------------------------------------------------------------
# 纯函数：路径提取 / multipart 编码 / FLAC 编码
# ---------------------------------------------------------------------------

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)((?:\[\d+\])*)")


def extract_text(payload: Any, path: str) -> str:
    """按点号 + 下标的路径从响应 JSON 中取出转写文本。

    支持 ``text``、``results[0].transcript``、``$.output.text`` 等写法。
    """
    if not path:
        raise AsrApiError("empty", "响应文本提取路径为空")

    clean = path.strip()
    if clean.startswith("$."):
        clean = clean[2:]
    elif clean.startswith("$"):
        clean = clean[1:].lstrip(".")

    current = payload
    for match in _PATH_TOKEN_RE.finditer(clean):
        name, indexes = match.group(1), match.group(2)
        if isinstance(current, dict):
            if name not in current:
                raise AsrApiError("empty", f"响应中不存在字段 {path!r}（缺少 {name}）")
            current = current[name]
        else:
            raise AsrApiError("empty", f"响应中不存在字段 {path!r}（{name} 之前不是对象）")

        if indexes:
            for idx_text in re.findall(r"\[(\d+)\]", indexes):
                idx = int(idx_text)
                if not isinstance(current, (list, tuple)) or idx >= len(current):
                    raise AsrApiError(
                        "empty", f"响应中不存在字段 {path!r}（下标 {idx} 越界）"
                    )
                current = current[idx]

    if isinstance(current, str):
        return current.strip()
    if isinstance(current, (list, tuple)):
        parts = []
        for item in current:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(p.strip() for p in parts if p.strip()).strip()
    if current is None:
        return ""
    return str(current).strip()


def build_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    boundary: str,
) -> bytes:
    """构造 ``multipart/form-data`` 请求体。

    fields: 名称 → 值；files: 名称 → (文件名, 内容, MIME 类型)。
    """
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(f"--{boundary}\r\n".encode())
        out.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        out.write(str(value).encode("utf-8"))
        out.write(b"\r\n")
    for name, (filename, content, mime) in files.items():
        out.write(f"--{boundary}\r\n".encode())
        out.write(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        out.write(f"Content-Type: {mime}\r\n\r\n".encode())
        out.write(content)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue()


def encode_flac(audio: np.ndarray, sample_rate: int) -> bytes:
    """把 float32 PCM 编码成 FLAC 内存流。"""
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="FLAC")
    return buf.getvalue()


def parse_custom_headers(raw: str, api_key: str) -> dict[str, str]:
    """解析自定义请求头 JSON，并替换其中的 ``{API_KEY}`` 占位符。"""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise AsrApiError("http", f"自定义请求头不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise AsrApiError("http", "自定义请求头必须是一个 JSON 对象")
    headers: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise AsrApiError("http", "自定义请求头的名值都必须是字符串")
        headers[key] = str(value).replace(API_KEY_PLACEHOLDER, api_key)
    return headers


def endpoint_url(api: ApiConfig) -> str:
    base = (api.base_url or "").strip().rstrip("/")
    path = (api.endpoint_path or "/audio/transcriptions").strip()
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def describe_http_error(exc: urllib.error.HTTPError) -> AsrApiError:
    """把 HTTP 状态码映射成带明确中文提示的错误。"""
    status = exc.code
    detail = ""
    try:
        raw = exc.read().decode("utf-8", "replace")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            elif isinstance(err, str):
                detail = err
            if not detail:
                detail = str(payload.get("message") or payload.get("detail") or "")
        if not detail:
            detail = raw
    except Exception:
        detail = ""
    detail = detail.strip()[:300]

    if status in (401, 403):
        msg = "API 密钥无效或未激活，请核查 Secret Key"
        if detail:
            msg += f"（{detail}）"
        return AsrApiError("auth", msg, status)
    if status == 429:
        msg = "账户配额不足或请求频率超限"
        if detail:
            msg += f"（{detail}）"
        return AsrApiError("rate_limit", msg, status)
    if status == 400:
        msg = "请求被拒绝（400）：请检查模型名、音频格式与响应提取字段"
        if detail:
            msg += f"（{detail}）"
        return AsrApiError("http", msg, status)
    msg = f"服务返回 HTTP {status} 错误"
    if detail:
        msg += f"：{detail}"
    return AsrApiError("http", msg, status)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

Opener = Callable[..., Any]


class OpenAICompatibleAsrEngine:
    """实现 ``asr.base.ASREngine`` 协议，调用远程 OpenAI 兼容端点。"""

    def __init__(
        self,
        cfg: AsrConfig,
        api_key: str | None,
        *,
        opener: Opener | None = None,
    ) -> None:
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError(
                "云端 ASR 需要 API Key：请在“API 配置”页面填写并保存（密钥存于本地 secrets.json）"
            )
        self._cfg = cfg
        self._api = cfg.api
        self._api_key = api_key
        self._opener = opener or urllib.request.urlopen
        self.name = f"api/{self._api.model or self._api.template}"

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if audio.size == 0:
            return ""
        if sample_rate != SAMPLE_RATE:
            raise ValueError(
                f"云端 ASR 只接受 {SAMPLE_RATE}Hz 音频，实际 {sample_rate}Hz"
            )

        flac = encode_flac(audio, sample_rate)

        fields: dict[str, str] = {
            "model": self._api.model,
            "response_format": "json",
        }
        if self._cfg.language:
            fields["language"] = self._cfg.language

        headers = {"Authorization": f"Bearer {self._api_key}"}
        headers.update(parse_custom_headers(self._api.custom_headers_json, self._api_key))

        boundary = "----VoiceNoteBoundary" + uuid.uuid4().hex
        body = build_multipart(
            fields,
            {"file": ("audio.flac", flac, "audio/flac")},
            boundary,
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        request = urllib.request.Request(
            endpoint_url(self._api), data=body, headers=headers, method="POST"
        )

        raw = self._request(request)
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise AsrApiError("parse", f"服务响应不是合法 JSON：{exc}") from exc

        return extract_text(payload, self._api.response_text_path)

    def _request(self, request: urllib.request.Request) -> bytes:
        timeout = self._api.timeout_s
        try:
            with self._opener(request, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise describe_http_error(exc) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise AsrApiError(
                    "timeout", f"请求超时（{timeout}s），请检查网络或调大超时时间"
                ) from exc
            raise AsrApiError(
                "connection", f"无法连接 Base URL，请检查网络代理或地址拼写：{reason}"
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AsrApiError(
                "timeout", f"请求超时（{timeout}s），请检查网络或调大超时时间"
            ) from exc
        except ssl.SSLError as exc:
            raise AsrApiError("connection", f"TLS 连接失败：{exc}") from exc
        except OSError as exc:
            raise AsrApiError("connection", f"网络错误：{exc}") from exc

    def warmup(self) -> None:
        """云端引擎不需要本地预热。"""
        return None


# ---------------------------------------------------------------------------
# 连通性测试
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    ok: bool
    kind: str
    message: str
    elapsed_ms: int


def load_connection_sample() -> np.ndarray:
    """连通性测试用的样例音频（16kHz float32）。

    优先用随包/仓库自带的 selftest 样例（约 3 秒真实语音）；找不到时合成
    一段 1 秒的类语音信号 —— 测试的是"连接和解析对不对"，不是识别准确率，
    没有网络时不应该因此失败。
    """
    for candidate in _sample_candidates():
        try:
            import soundfile as sf

            audio, rate = sf.read(candidate, dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if rate != SAMPLE_RATE:
                n = int(audio.shape[0] * SAMPLE_RATE / rate)
                audio = np.interp(
                    np.linspace(0, audio.shape[0] - 1, n),
                    np.arange(audio.shape[0]),
                    audio,
                )
            return np.asarray(audio, dtype=np.float32)
        except Exception as exc:
            log.debug("样例音频不可用 %s：%s", candidate, exc)
            continue

    log.info("未找到自检样例，连通性测试改用合成音频")
    n = SAMPLE_RATE
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    envelope = 0.4 * (1.0 + np.sin(2 * np.pi * 0.8 * t))
    return (np.sin(2 * np.pi * 220.0 * t) * envelope).astype(np.float32)


def _sample_candidates() -> list[Path]:
    candidates: list[Path] = []
    try:
        candidates.append(bundle_root() / SAMPLE_FILENAME)
    except Exception:
        pass
    try:
        root = project_root()
        if root is not None:
            candidates.append(root / "packaging" / SAMPLE_FILENAME)
    except Exception:
        pass
    return candidates


def test_connection(
    asr_cfg: AsrConfig,
    api_key: str,
    *,
    sample: np.ndarray | None = None,
    engine_factory: Callable[..., OpenAICompatibleAsrEngine] | None = None,
) -> ConnectionTestResult:
    """用样例音频发一次真实请求，返回可读的测试结果。"""
    factory = engine_factory or OpenAICompatibleAsrEngine
    t0 = time.perf_counter()

    if not (api_key or "").strip():
        return ConnectionTestResult(
            False, "no_key", "尚未填写 API 密钥，无法测试", 0
        )

    try:
        audio = sample if sample is not None else load_connection_sample()
    except Exception as exc:
        return ConnectionTestResult(False, "connection", f"无法准备测试音频：{exc}", 0)

    try:
        engine = factory(asr_cfg, api_key)
        text = engine.transcribe(audio, SAMPLE_RATE)
    except AsrApiError as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        return ConnectionTestResult(False, exc.kind, str(exc), elapsed)
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        return ConnectionTestResult(False, "connection", f"测试失败：{exc}", elapsed)

    elapsed = int((time.perf_counter() - t0) * 1000)
    if not text:
        return ConnectionTestResult(
            True,
            "empty",
            f"连通成功（{elapsed}ms），但样例音频未识别出文本，请核对响应提取字段",
            elapsed,
        )
    return ConnectionTestResult(
        True, "ok", f"连通成功（{elapsed}ms）：{text[:80]}", elapsed
    )
