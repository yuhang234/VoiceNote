"""NVIDIA Parakeet TDT ASR (nemo_toolkit backend).

Parakeet TDT is NVIDIA's open-source ASR model family, the same tech stack
used by OpenSuperWhisper / Handy.  V3 supports 25 European languages with
automatic language detection; English recognition is extremely fast and
accurate (RTF < 0.05), and on CPU it is several times faster than Whisper.
Chinese is not supported by this model, so keep Whisper for Chinese speech.

Dependency:
    pip install "nemo_toolkit[asr]"

The model is auto-downloaded by NeMo from HuggingFace / NVIDIA NGC on first
load, so it does not go through VoiceNote's huggingface_hub download flow.

Interface is identical to FasterWhisperEngine:
    transcribe(float32 audio, sample_rate) -> str
"""

from __future__ import annotations

import logging
import os
import tempfile

import numpy as np

from ..config import AsrConfig
from .base import SAMPLE_RATE

log = logging.getLogger(__name__)

_NOT_INSTALLED = (
    "Parakeet engine requires nemo_toolkit: "
    'pip install "nemo_toolkit[asr]". '
    "After installing, switch to the Parakeet model in the Local Models page."
)

_NEMO_MODEL_MAP = {
    "parakeet-tdt-0.6b-v3": "nvidia/parakeet-tdt-0.6b-v3",
    # 保留 V2 映射，方便已有 config.toml 继续加载。
    "parakeet-tdt-0.6b-v2": "nvidia/parakeet-tdt-0.6b-v2",
    "parakeet-tdt-1.1b": "nvidia/parakeet-tdt-1.1b",
}


class ParakeetEngine:
    """NVIDIA Parakeet TDT ASR engine."""

    def __init__(self, cfg: AsrConfig) -> None:
        try:
            from nemo.collections.asr.models import ASRModel
        except ImportError as exc:
            raise ImportError(_NOT_INSTALLED) from exc

        self._cfg = cfg
        model_id = cfg.model or "parakeet-tdt-0.6b-v3"
        nemo_name = _NEMO_MODEL_MAP.get(model_id, model_id)
        self.name = f"parakeet/{model_id}"

        log.info("Loading Parakeet model %s ...", nemo_name)
        device = cfg.device if cfg.device in ("cuda", "cpu") else "cpu"
        self._model = ASRModel.from_pretrained(model_name=nemo_name)
        if device == "cuda":
            try:
                import torch

                if torch.cuda.is_available():
                    self._model = self._model.to("cuda")
                else:
                    log.warning("CUDA not available, Parakeet falls back to CPU")
            except Exception as exc:
                log.warning("Failed to move Parakeet to GPU, using CPU: %s", exc)
        log.info("Parakeet model loaded: %s", self.name)

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(
                f"Parakeet requires {SAMPLE_RATE}Hz audio, got {sample_rate}Hz"
            )
        if audio.size == 0:
            return ""

        import soundfile as sf

        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sf.write(tmp_path, audio, SAMPLE_RATE, subtype="PCM_16")
            result = self._model.transcribe([tmp_path])
            if isinstance(result, list) and result:
                first = result[0]
                if isinstance(first, str):
                    return first.strip()
                return getattr(first, "text", str(first)).strip()
            if isinstance(result, str):
                return result.strip()
            return str(result).strip()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def warmup(self) -> None:
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE)
