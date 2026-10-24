"""ASR engine factory.

Three engine types are supported:
  - ``faster_whisper``: local offline Whisper via CTranslate2 (default).
  - ``parakeet``: local offline NVIDIA Parakeet TDT via nemo_toolkit.
  - ``api``: cloud OpenAI-compatible transcription endpoint.

The Qwen3-ASR engine (``qwen3_engine.py``) is still a placeholder.
"""

from __future__ import annotations

from ..config import AsrConfig
from .base import ASREngine

__all__ = ["ASREngine", "create_engine"]


def create_engine(cfg: AsrConfig, *, api_key: str | None = None) -> ASREngine:
    if cfg.engine == "faster_whisper":
        from .faster_whisper_engine import FasterWhisperEngine

        return FasterWhisperEngine(cfg)

    if cfg.engine == "parakeet":
        from .parakeet_engine import ParakeetEngine

        return ParakeetEngine(cfg)

    if cfg.engine == "api":
        from .openai_api_engine import OpenAICompatibleAsrEngine

        return OpenAICompatibleAsrEngine(cfg, api_key)

    # qwen3 的实现在 qwen3_engine.py，目前是占位。
    raise ValueError(f"unknown ASR engine: {cfg.engine!r}")
