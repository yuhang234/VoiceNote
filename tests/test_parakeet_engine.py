"""Parakeet engine adapter tests (no NeMo installation required)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

from voicenote.asr import create_engine
from voicenote.config import AsrConfig


class _Hypothesis:
    text = "  hello from parakeet  "


class _FakeASRModel:
    requested: list[str] = []

    @classmethod
    def from_pretrained(cls, *, model_name: str):
        cls.requested.append(model_name)
        return cls()

    def transcribe(self, paths: list[str]):
        assert len(paths) == 1
        assert Path(paths[0]).is_file()
        return [_Hypothesis()]


def _install_fake_nemo(monkeypatch) -> None:
    nemo = types.ModuleType("nemo")
    nemo.__path__ = []
    collections = types.ModuleType("nemo.collections")
    collections.__path__ = []
    asr = types.ModuleType("nemo.collections.asr")
    asr.__path__ = []
    models = types.ModuleType("nemo.collections.asr.models")
    models.ASRModel = _FakeASRModel

    monkeypatch.setitem(sys.modules, "nemo", nemo)
    monkeypatch.setitem(sys.modules, "nemo.collections", collections)
    monkeypatch.setitem(sys.modules, "nemo.collections.asr", asr)
    monkeypatch.setitem(sys.modules, "nemo.collections.asr.models", models)


def test_parakeet_v3_factory_and_transcription(monkeypatch):
    _install_fake_nemo(monkeypatch)
    _FakeASRModel.requested.clear()
    cfg = AsrConfig(
        engine="parakeet",
        model="parakeet-tdt-0.6b-v3",
        device="cpu",
    )

    engine = create_engine(cfg)

    assert engine.name == "parakeet/parakeet-tdt-0.6b-v3"
    assert _FakeASRModel.requested == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert engine.transcribe(np.zeros(1600, dtype=np.float32), 16000) == (
        "hello from parakeet"
    )
    assert engine.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""
