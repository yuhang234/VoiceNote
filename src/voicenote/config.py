"""配置加载与保存：TOML 文件 ↔ 带默认值的数据类。

未知的配置项会被忽略并记一条警告，而不是直接报错 —— 这样旧配置文件
在新增/改名配置项后仍然能用。

写回用的是本模块自带的极简 TOML 序列化（``save``/``dumps``），不引入额外
依赖：配置结构是固定的，值只有字符串/布尔/整数/浮点四种。
"""

from __future__ import annotations

import json
import logging
import tomllib
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from . import APP_NAME

log = logging.getLogger(__name__)

T = TypeVar("T")

#: 关闭主窗口时的行为。
CLOSE_ACTIONS = ("minimize_to_tray", "exit")
#: 本地引擎与云端 OpenAI 兼容引擎。
ASR_ENGINES = ("faster_whisper", "api")

CONFIG_NAME = "config.toml"


class ConfigError(Exception):
    """配置文件本身有问题（类型不对、值非法）。"""


def default_data_dir() -> Path:
    return Path.home() / APP_NAME


def default_config_path() -> Path:
    return default_data_dir() / CONFIG_NAME


@dataclass(slots=True)
class GeneralConfig:
    data_dir: str = ""
    # 模型下载源。默认走国内镜像 —— 官方 huggingface.co 在国内经常不通，
    # 而打包版第一次启动必须下 1.6GB 权重。填 "" 即走官方源。
    hf_endpoint: str = "https://hf-mirror.com"
    # 启动时是否自动打开主界面（false = 仅托盘静默启动）。
    open_ui_on_startup: bool = False
    # 关闭主窗口时的行为："minimize_to_tray"（隐藏到托盘，继续录音）或 "exit"。
    close_action: str = "minimize_to_tray"

    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).expanduser() if self.data_dir else default_data_dir()


@dataclass(slots=True)
class AudioConfig:
    enabled: bool = True
    device: str = ""
    sample_rate: int = 16_000
    # 32ms = 512 个采样点，正好是 silero-vad 在 16kHz 下的固定窗口长度。
    # 对齐这个值可以省掉一层重新分块的缓冲逻辑。
    block_ms: int = 32

    @property
    def block_samples(self) -> int:
        return self.sample_rate * self.block_ms // 1000


@dataclass(slots=True)
class VadConfig:
    speech_threshold: float = 0.5
    min_speech_ms: int = 250
    min_silence_ms: int = 700
    max_segment_s: int = 20
    pre_roll_ms: int = 300
    speech_pad_ms: int = 200


@dataclass(slots=True)
class ApiConfig:
    """云端 ASR（OpenAI 兼容）的连接参数。

    API Key **不在这里**：它由 ``secret_store.SecretStore`` 存到
    ``<data_dir>/state/secrets.json``，绝不写进 config.toml，
    避免用户分享配置或提 PR 时把密钥带出去。
    """

    # 厂商模板标识：siliconflow / groq / openai / dashscope / custom。
    template: str = "siliconflow"
    base_url: str = "https://api.siliconflow.cn/v1"
    # OpenAI 音频转写端点相对路径，非标准网关可在此调整。
    endpoint_path: str = "/audio/transcriptions"
    model: str = "FunAudioLLM/SenseVoiceSmall"
    timeout_s: int = 30
    # 响应 JSON 中文本的提取路径（点号 + 下标），如 text 或 results[0].transcript。
    response_text_path: str = "text"
    # 自定义请求头（JSON 字符串）。值里的 {API_KEY} 会被替换成真实密钥；
    # 留空时使用标准 `Authorization: Bearer <key>`。
    custom_headers_json: str = ""


@dataclass(slots=True)
class AsrConfig:
    engine: str = "faster_whisper"
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "int8_float16"
    language: str = ""
    beam_size: int = 1
    initial_prompt: str = ""
    api: ApiConfig = field(default_factory=ApiConfig)


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(slots=True)
class Config:
    general: GeneralConfig
    audio: AudioConfig
    vad: VadConfig
    asr: AsrConfig
    logging: LoggingConfig

    @property
    def data_dir(self) -> Path:
        return self.general.resolved_data_dir()

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def copy(self) -> Config:
        """深拷贝一份配置，供设置界面“取消”语义使用。"""
        import copy as _copy

        return _copy.deepcopy(self)


def _section(cls: type[T], raw: dict[str, Any], name: str) -> T:
    section = raw.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] 必须是一个配置表，实际是 {type(section).__name__}")

    allowed = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    for key in section:
        if key not in allowed:
            log.warning("未知配置项 [%s].%s，已忽略", name, key)

    kwargs: dict[str, Any] = {}
    for key, value in section.items():
        f = allowed.get(key)
        if f is None:
            continue
        nested = _nested_dataclass(f)
        if nested is not None:
            if not isinstance(value, dict):
                raise ConfigError(
                    f"[{name}.{key}] 必须是一个配置表，实际是 {type(value).__name__}"
                )
            kwargs[key] = _section(nested, section, key)
        else:
            kwargs[key] = value
    return cls(**kwargs)  # type: ignore[call-arg]


def _nested_dataclass(f: Any) -> type | None:
    """字段用 default_factory 指向另一个 dataclass 时，把它当子表处理。"""
    factory = getattr(f, "default_factory", MISSING)
    if factory is MISSING:
        return None
    return factory if is_dataclass(factory) else None


def load(path: Path | None = None) -> Config:
    """读取配置文件。路径不存在时使用全默认配置（只记一条警告）。"""
    raw: dict[str, Any] = {}
    if path is not None:
        if path.is_file():
            with path.open("rb") as fh:
                try:
                    raw = tomllib.load(fh)
                except tomllib.TOMLDecodeError as exc:
                    raise ConfigError(f"配置文件解析失败：{path}\n{exc}") from exc
        else:
            log.warning("配置文件不存在：%s，使用默认配置", path)

    cfg = Config(
        general=_section(GeneralConfig, raw, "general"),
        audio=_section(AudioConfig, raw, "audio"),
        vad=_section(VadConfig, raw, "vad"),
        asr=_section(AsrConfig, raw, "asr"),
        logging=_section(LoggingConfig, raw, "logging"),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.audio.sample_rate <= 0:
        raise ConfigError("audio.sample_rate 必须为正数")
    if cfg.audio.block_samples <= 0:
        raise ConfigError("audio.block_ms 太小，算出来每个音频块不足 1 个采样点")
    if not 0.0 < cfg.vad.speech_threshold < 1.0:
        raise ConfigError("vad.speech_threshold 必须在 0 和 1 之间")
    if cfg.vad.min_silence_ms <= 0:
        raise ConfigError("vad.min_silence_ms 必须为正数")
    if cfg.vad.max_segment_s <= 0:
        raise ConfigError("vad.max_segment_s 必须为正数")
    if cfg.general.close_action not in CLOSE_ACTIONS:
        raise ConfigError(
            f"general.close_action 只能是 {' 或 '.join(CLOSE_ACTIONS)}，"
            f"实际是 {cfg.general.close_action!r}"
        )
    if cfg.asr.device not in {"cuda", "cpu"}:
        raise ConfigError(f"asr.device 只能是 cuda 或 cpu，实际是 {cfg.asr.device!r}")
    if cfg.asr.engine not in ASR_ENGINES:
        raise ConfigError(
            f"asr.engine 只支持 {' 或 '.join(ASR_ENGINES)}，实际是 {cfg.asr.engine!r}"
        )
    if cfg.asr.beam_size < 1:
        raise ConfigError("asr.beam_size 必须 >= 1")
    # [asr.api] 始终校验：即使当前用本地引擎，配置里写坏了也要在加载时报错，
    # 否则用户切到云端引擎时才会在运行时炸，难以定位。
    _validate_api(cfg.asr.api)


def _validate_api(api: ApiConfig) -> None:
    if not api.base_url.strip():
        raise ConfigError("asr.api.base_url 不能为空")
    if not api.model.strip():
        raise ConfigError("asr.api.model 不能为空")
    if api.timeout_s <= 0:
        raise ConfigError("asr.api.timeout_s 必须为正数")
    if not api.response_text_path.strip():
        raise ConfigError("asr.api.response_text_path 不能为空（默认 text）")
    if api.custom_headers_json.strip():
        import json as _json

        try:
            parsed = _json.loads(api.custom_headers_json)
        except ValueError as exc:
            raise ConfigError(f"asr.api.custom_headers_json 不是合法 JSON：{exc}") from exc
        if not isinstance(parsed, dict):
            raise ConfigError("asr.api.custom_headers_json 必须是一个 JSON 对象")


def validate_api(api: ApiConfig) -> None:
    """供设置界面在保存前做与加载时一致的校验。"""
    _validate_api(api)


# ---------------------------------------------------------------------------
# 写回 TOML
# ---------------------------------------------------------------------------


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        # json.dumps 产出的转义规则与 TOML basic string 兼容（不含 \/ 转义）。
        return json.dumps(value, ensure_ascii=False)
    raise ConfigError(f"无法写入配置值：{value!r}（{type(value).__name__}）")


def dumps(cfg: Config) -> str:
    """把配置序列化成 TOML 文本。"""
    lines: list[str] = ["# VoiceNote 配置（由程序自动生成，可手工编辑）", ""]

    def section(name: str) -> None:
        lines.append(f"[{name}]")

    def kv(key: str, value: Any) -> None:
        lines.append(f"{key} = {_toml_value(value)}")

    section("general")
    kv("data_dir", cfg.general.data_dir)
    kv("hf_endpoint", cfg.general.hf_endpoint)
    kv("open_ui_on_startup", cfg.general.open_ui_on_startup)
    kv("close_action", cfg.general.close_action)
    lines.append("")

    section("audio")
    kv("enabled", cfg.audio.enabled)
    kv("device", cfg.audio.device)
    kv("sample_rate", cfg.audio.sample_rate)
    kv("block_ms", cfg.audio.block_ms)
    lines.append("")

    section("vad")
    kv("speech_threshold", cfg.vad.speech_threshold)
    kv("min_speech_ms", cfg.vad.min_speech_ms)
    kv("min_silence_ms", cfg.vad.min_silence_ms)
    kv("max_segment_s", cfg.vad.max_segment_s)
    kv("pre_roll_ms", cfg.vad.pre_roll_ms)
    kv("speech_pad_ms", cfg.vad.speech_pad_ms)
    lines.append("")

    section("asr")
    kv("engine", cfg.asr.engine)
    kv("model", cfg.asr.model)
    kv("device", cfg.asr.device)
    kv("compute_type", cfg.asr.compute_type)
    kv("language", cfg.asr.language)
    kv("beam_size", cfg.asr.beam_size)
    kv("initial_prompt", cfg.asr.initial_prompt)
    lines.append("")

    section("asr.api")
    kv("template", cfg.asr.api.template)
    kv("base_url", cfg.asr.api.base_url)
    kv("endpoint_path", cfg.asr.api.endpoint_path)
    kv("model", cfg.asr.api.model)
    kv("timeout_s", cfg.asr.api.timeout_s)
    kv("response_text_path", cfg.asr.api.response_text_path)
    kv("custom_headers_json", cfg.asr.api.custom_headers_json)
    lines.append("")

    section("logging")
    kv("level", cfg.logging.level)
    lines.append("")
    return "\n".join(lines)


def save(cfg: Config, path: Path) -> None:
    """把配置写回 TOML 文件（先写临时文件再原子替换）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(dumps(cfg), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
