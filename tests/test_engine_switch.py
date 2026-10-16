"""Application 核心逻辑测试（不依赖 Qt）：ASR 热切换、加载竞争、配置保存。

用假引擎工厂注入，验证：
- switch_engine 先建新再换旧，失败时旧引擎原地保留；
- 手动切换与首次加载竞争时，加载结果被正确丢弃（不覆盖用户选择）；
- API Key 从 SecretStore 注入到引擎工厂，而不是从配置文件读。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from voicenote import config as config_module
from voicenote.app import Application
from voicenote.config import AsrConfig, load
from voicenote.secret_store import SecretStore
from voicenote.status import IconState


class FakeEngine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.warmups = 0

    def warmup(self) -> None:
        self.warmups += 1

    def transcribe(self, audio, sample_rate):  # pragma: no cover - 未在测试中使用
        return ""


def make_app(tmp_path: Path):
    cfg = load(None)
    cfg.general.data_dir = str(tmp_path / "data")
    calls: list[tuple[AsrConfig, str | None]] = []

    def factory(asr_cfg: AsrConfig, *, api_key: str | None = None) -> Any:
        if asr_cfg.model == "explode":
            raise RuntimeError("加载失败（测试用）")
        calls.append((asr_cfg, api_key))
        return FakeEngine(f"fake/{asr_cfg.engine}/{asr_cfg.model}")

    secrets = SecretStore(cfg.state_dir)
    app = Application(
        cfg,
        config_path=tmp_path / "config.toml",
        engine_factory=factory,
        secrets=secrets,
    )
    return app, cfg, secrets, calls


def test_switch_engine_success(tmp_path):
    app, cfg, _, calls = make_app(tmp_path)
    new_cfg = AsrConfig(engine="faster_whisper", model="small")

    assert app.switch_engine(new_cfg) is True
    assert app._engine is not None
    assert app._engine.warmups == 1
    assert cfg.asr.model == "small"
    assert app.active_engine_name == "fake/faster_whisper/small"
    assert calls and calls[0][0].model == "small"
    assert calls[0][1] is None  # 本地引擎不需要 key

    app._stopping.set()
    if app._asr_thread is not None:
        app._asr_thread.join(timeout=2.0)


def test_switch_engine_failure_keeps_old_engine(tmp_path):
    app, cfg, _, _ = make_app(tmp_path)
    assert app.switch_engine(AsrConfig(engine="faster_whisper", model="tiny")) is True
    old_engine = app._engine

    failed = AsrConfig(engine="faster_whisper", model="explode")
    assert app.switch_engine(failed) is False
    assert app._engine is old_engine  # 旧引擎原地保留
    assert cfg.asr.model == "tiny"  # 配置也没被改
    assert app.state is IconState.ERROR

    app._stopping.set()
    if app._asr_thread is not None:
        app._asr_thread.join(timeout=2.0)


def test_switch_engine_passes_api_key_from_secrets(tmp_path):
    app, cfg, secrets, calls = make_app(tmp_path)
    secrets.set_api_key("default", "sk-from-store")

    new_cfg = AsrConfig(engine="api")
    new_cfg.api.base_url = "https://api.example.com/v1"
    new_cfg.api.model = "whisper-1"

    assert app.switch_engine(new_cfg) is True
    assert calls and calls[-1][1] == "sk-from-store"

    app._stopping.set()
    if app._asr_thread is not None:
        app._asr_thread.join(timeout=2.0)


def test_load_engine_success(tmp_path):
    app, cfg, _, calls = make_app(tmp_path)
    assert app._load_engine() is True
    assert app._engine is not None
    assert app.active_engine_name.startswith("fake/faster_whisper/")
    assert app.state is IconState.LISTENING


def test_load_engine_failure(tmp_path):
    app, cfg, _, _ = make_app(tmp_path)
    cfg.asr.model = "explode"
    assert app._load_engine() is False
    assert app._engine is None
    assert app.state is IconState.ERROR


def test_load_engine_discarded_when_user_switched(tmp_path):
    """加载期间用户手动切换：加载结果必须丢弃，不能覆盖用户的引擎。"""
    app, cfg, _, _ = make_app(tmp_path)

    # 模拟“加载过程中用户点了切换”：工厂执行时抬高 epoch
    def racing_factory(asr_cfg, *, api_key=None):
        app._engine_epoch += 1
        return FakeEngine("racing")

    app._engine_factory = racing_factory
    assert app._load_engine() is True  # 返回 True：继续消费队列
    assert app._engine is None  # 但不能写入 self._engine


def test_pause_resume_without_audio(tmp_path):
    app, cfg, _, _ = make_app(tmp_path)
    app.pause()
    assert app.paused is True
    assert app.state is IconState.PAUSED
    app.resume()
    assert app.paused is False
    assert app.state is IconState.LISTENING


def test_save_config_roundtrip(tmp_path):
    app, cfg, _, _ = make_app(tmp_path)
    cfg.general.close_action = "exit"
    cfg.general.open_ui_on_startup = True
    cfg.asr.api.base_url = "https://api.groq.com/openai/v1"
    cfg.asr.api.model = "whisper-large-v3-turbo"

    path = app.save_config()
    assert path is not None and Path(path).is_file()

    reloaded = config_module.load(Path(path))
    assert reloaded.general.close_action == "exit"
    assert reloaded.general.open_ui_on_startup is True
    assert reloaded.asr.api.base_url == "https://api.groq.com/openai/v1"
    assert reloaded.asr.api.model == "whisper-large-v3-turbo"


def test_api_key_helper(tmp_path):
    app, cfg, secrets, _ = make_app(tmp_path)
    assert app.api_key() is None
    secrets.set_api_key("default", "sk-abc")
    assert app.api_key() == "sk-abc"


def test_open_today_without_ui_is_noop(tmp_path):
    app, cfg, _, _ = make_app(tmp_path)
    app.open_today()  # 没有 UI 时不应抛异常
