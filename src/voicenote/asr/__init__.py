"""ASR 引擎选择。"""

from __future__ import annotations

from ..config import AsrConfig
from .base import ASREngine

__all__ = ["ASREngine", "create_engine"]


def create_engine(cfg: AsrConfig, *, api_key: str | None = None) -> ASREngine:
    if cfg.engine == "faster_whisper":
        from .faster_whisper_engine import FasterWhisperEngine

        return FasterWhisperEngine(cfg)

    if cfg.engine == "api":
        from .openai_api_engine import OpenAICompatibleAsrEngine

        return OpenAICompatibleAsrEngine(cfg, api_key)

    # qwen3 的实现在 qwen3_engine.py，目前是占位。
    raise ValueError(f"未知的 ASR 引擎：{cfg.engine!r}")
