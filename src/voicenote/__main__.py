"""VoiceNote 入口。

    python -m voicenote             # 启动（托盘常驻 + 主界面）
    python -m voicenote --check     # 体检环境并打印配置，不启动
    python -m voicenote --selftest  # 跑一次端到端自检后退出

打包成无控制台的 exe 之后 sys.stdout / sys.stderr 都是 None，
所以本模块所有输出都要经过 ``_emit``，不能直接 print。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__, paths
from .config import Config, ConfigError, default_data_dir, load
from .cuda_env import register_cuda_dlls
from .logging_setup import setup_logging

log = logging.getLogger(__name__)

CONFIG_NAME = "config.toml"


def _emit(lines: list[str]) -> None:
    """把一段文本同时送进日志和 stdout。

    打包版（--windowed）里 sys.stdout 是 None，直接 print 会抛 TypeError。
    这类版本没有控制台，日志文件是唯一能看到输出的地方。
    """
    for line in lines:
        log.info("%s", line)
    if sys.stdout is not None:
        print("\n".join(lines))


def _report_startup_error(message: str) -> None:
    """启动早期出错时的兜底输出。

    此时日志系统可能还没起来，所以优先直接写 stderr；
    无控制台的打包版 stderr 是 None，只能落到数据目录的日志文件里 ——
    否则用户遇到的就是"双击了没反应，什么也看不到"。
    """
    if sys.stderr is not None:
        print(message, file=sys.stderr)
        return
    try:
        fallback = default_data_dir() / "logs" / "startup-error.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        with fallback.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except Exception:
        pass


def project_root() -> Path | None:
    """源码树根目录。冻结后没有这个概念。"""
    return paths.project_root()


def find_config(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    # 只有源码运行时才去找项目根目录的 config.toml；打包后那一层不存在，
    # 配置一律从数据目录读。
    root = project_root()
    if root is not None:
        local = root / CONFIG_NAME
        if local.is_file():
            return local
    return default_data_dir() / CONFIG_NAME


def _audio_device_lines(cfg: Config) -> list[str]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        return [f"音频设备：sounddevice 未安装（{exc}）"]

    try:
        devices = sd.query_devices()
        default_in = sd.default.device[0]
    except Exception as exc:
        return [f"音频设备：枚举失败：{exc}"]

    lines = [f"音频设备（默认输入 #{default_in}）："]
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] < 1:
            continue
        marker = "*" if idx == default_in else " "
        lines.append(
            f"  {marker} #{idx:<3} {dev['name']}"
            f"  ({dev['max_input_channels']}ch, {int(dev['default_samplerate'])}Hz)"
        )
    if cfg.audio.device:
        matches = [d for d in devices if cfg.audio.device.lower() in d["name"].lower()]
        lines.append(f"  配置的 device={cfg.audio.device!r} 匹配到 {len(matches)} 个输入设备")
    return lines


def run_check(cfg: Config) -> int:
    lines = [
        f"{APP_NAME} {__version__}",
        f"运行方式     : {'打包版（冻结）' if paths.is_frozen() else '源码'}",
        f"Python       : {sys.version.split()[0]}  ({sys.executable})",
        f"数据目录      : {cfg.data_dir}",
        f"配置文件      : {find_config(None) or '(默认)'}",
    ]

    registered = register_cuda_dlls()
    lines.append(f"CUDA DLL 目录 : {len(registered)} 个")
    lines.extend(f"               {d}" for d in registered)

    try:
        import ctranslate2

        lines.append(
            f"ctranslate2  : {ctranslate2.__version__}"
            f"（可见 CUDA 设备 {ctranslate2.get_cuda_device_count()}）"
        )
    except ImportError as exc:
        lines.append(f"ctranslate2  : 未安装（{exc}）")

    lines.append("")
    lines.extend(_audio_device_lines(cfg))

    api = cfg.asr.api
    try:
        from .secret_store import SecretStore

        has_key = SecretStore(cfg.state_dir).has_api_key()
    except Exception:
        has_key = False

    lines.extend(
        [
            "",
            "ASR 配置     :",
            f"  engine      = {cfg.asr.engine}",
            f"  model       = {cfg.asr.model}",
            f"  device      = {cfg.asr.device}",
            f"  compute_type= {cfg.asr.compute_type}",
            f"  language    = {cfg.asr.language or '(自动检测)'}",
            "",
            "云端 API 配置 :",
            f"  template    = {api.template}",
            f"  base_url    = {api.base_url}",
            f"  model       = {api.model}",
            f"  API Key     = {'已配置（state/secrets.json）' if has_key else '未配置'}",
            "",
            "VAD 分段      :",
            f"  阈值 {cfg.vad.speech_threshold}，静音 {cfg.vad.min_silence_ms}ms 断句，"
            f"最长 {cfg.vad.max_segment_s}s 强制切分",
            f"  最短语音 {cfg.vad.min_speech_ms}ms（更短的丢弃）",
            "",
            f"音频留存      : {'开启' if cfg.audio.enabled else '关闭'}",
            f"模型下载源    : {cfg.general.hf_endpoint or '(HuggingFace 官方)'}",
            f"关闭窗口行为  : {cfg.general.close_action}",
        ]
    )

    _emit(lines)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voicenote",
        description="低启动成本的电脑端语音记录工具",
    )
    parser.add_argument("--config", help="配置文件路径（默认项目根目录的 config.toml）")
    parser.add_argument("--check", action="store_true", help="只体检环境并打印配置，不启动")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="跑一次端到端自检后退出（用内置样例音频，不占用麦克风）",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    try:
        cfg = load(find_config(args.config))
    except ConfigError as exc:
        _report_startup_error(f"配置错误：{exc}")
        return 2

    setup_logging(cfg.logging.level, cfg.data_dir / "logs" / "voicenote.log")

    # 必须在导入 huggingface_hub 之前设置 —— 它在 import 的时候就把
    # HF_ENDPOINT 读进常量了，之后再设没有用。
    if cfg.general.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", cfg.general.hf_endpoint)

    if args.check:
        return run_check(cfg)

    if args.selftest:
        from .selfcheck import run_selfcheck

        return run_selfcheck(cfg)

    from .app import run

    return run(cfg, config_path=find_config(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
