"""配置加载 / 校验 / 写回的单元测试。

重点验证三件事：
1. 旧版 config.toml（没有新增字段）仍然能加载 —— 向后兼容；
2. 新字段（close_action、open_ui_on_startup、[asr.api]）能正确读取与校验；
3. save() → load() 往返不丢信息（设置界面就靠这条）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voicenote.config import (
    ASR_ENGINES,
    CLOSE_ACTIONS,
    ApiConfig,
    ConfigError,
    dumps,
    load,
    save,
    validate_api,
)

# 改动前的旧版配置样貌（除了 asr.api 外都是老字段），用来证明向后兼容。
OLD_CONFIG = """
[general]
data_dir = ""
hf_endpoint = "https://hf-mirror.com"

[audio]
enabled = true
device = ""
sample_rate = 16000
block_ms = 32

[vad]
speech_threshold = 0.5
min_speech_ms = 250
min_silence_ms = 700
max_segment_s = 20
pre_roll_ms = 300
speech_pad_ms = 200

[asr]
engine = "faster_whisper"
model = "large-v3-turbo"
device = "cuda"
compute_type = "int8_float16"
language = ""
beam_size = 1
initial_prompt = ""

[logging]
level = "INFO"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_file():
    cfg = load(None)
    assert cfg.general.close_action == "minimize_to_tray"
    assert cfg.general.open_ui_on_startup is False
    assert cfg.asr.engine == "faster_whisper"
    assert cfg.asr.api.base_url.startswith("https://")
    assert cfg.asr.api.response_text_path == "text"


def test_old_config_loads_with_new_defaults(tmp_path):
    cfg = load(write(tmp_path, OLD_CONFIG))
    assert cfg.asr.model == "large-v3-turbo"
    assert cfg.vad.min_silence_ms == 700
    # 新增字段自动取默认值
    assert cfg.general.close_action == "minimize_to_tray"
    assert cfg.general.open_ui_on_startup is False
    assert isinstance(cfg.asr.api, ApiConfig)


def test_api_section_loads(tmp_path):
    text = OLD_CONFIG + """
[asr.api]
template = "groq"
base_url = "https://api.groq.com/openai/v1"
model = "whisper-large-v3-turbo"
timeout_s = 42
response_text_path = "results[0].transcript"
custom_headers_json = "{\\"X-Test\\": \\"1\\"}"
"""
    cfg = load(write(tmp_path, text))
    api = cfg.asr.api
    assert api.template == "groq"
    assert api.timeout_s == 42
    assert api.response_text_path == "results[0].transcript"
    assert api.custom_headers_json == '{"X-Test": "1"}'


def test_unknown_keys_ignored(tmp_path):
    # 新增/改名的字段在旧配置里没有、或旧配置里有已删除的字段，都应忽略而不是报错。
    text = OLD_CONFIG.replace(
        'hf_endpoint = "https://hf-mirror.com"',
        'hf_endpoint = "https://hf-mirror.com"\nthis_key_never_existed = 1',
    )
    cfg = load(write(tmp_path, text))
    assert cfg.general.hf_endpoint == "https://hf-mirror.com"
    assert cfg.asr.engine == "faster_whisper"


@pytest.mark.parametrize("action", CLOSE_ACTIONS)
def test_close_action_valid(tmp_path, action):
    text = OLD_CONFIG.replace(
        'data_dir = ""', f'data_dir = ""\nclose_action = "{action}"'
    )
    cfg = load(write(tmp_path, text))
    assert cfg.general.close_action == action


def test_close_action_invalid(tmp_path):
    text = OLD_CONFIG.replace('data_dir = ""', 'data_dir = ""\nclose_action = "ask"')
    with pytest.raises(ConfigError):
        load(write(tmp_path, text))


def test_engine_api_accepted(tmp_path):
    text = OLD_CONFIG.replace('engine = "faster_whisper"', 'engine = "api"')
    cfg = load(write(tmp_path, text))
    assert cfg.asr.engine in ASR_ENGINES
    assert cfg.asr.engine == "api"


def test_engine_api_requires_base_url(tmp_path):
    text = OLD_CONFIG.replace('engine = "faster_whisper"', 'engine = "api"')
    text += '\n[asr.api]\nbase_url = ""\n'
    with pytest.raises(ConfigError):
        load(write(tmp_path, text))


def test_engine_bogus_rejected(tmp_path):
    text = OLD_CONFIG.replace('engine = "faster_whisper"', 'engine = "magic"')
    with pytest.raises(ConfigError):
        load(write(tmp_path, text))


def test_bad_custom_headers_json(tmp_path):
    text = OLD_CONFIG + '\n[asr.api]\ncustom_headers_json = "not json"\n'
    with pytest.raises(ConfigError):
        load(write(tmp_path, text))


def test_validate_api_helper():
    with pytest.raises(ConfigError):
        validate_api(ApiConfig(base_url=""))
    with pytest.raises(ConfigError):
        validate_api(ApiConfig(model=" "))
    validate_api(ApiConfig())  # 默认值合法


def test_roundtrip_dump_load(tmp_path):
    cfg = load(write(tmp_path, OLD_CONFIG))
    cfg.general.close_action = "exit"
    cfg.general.open_ui_on_startup = True
    cfg.asr.api.template = "openai"
    cfg.asr.api.base_url = "https://api.openai.com/v1"
    cfg.asr.api.model = "whisper-1"
    cfg.asr.api.response_text_path = "text"
    cfg.asr.api.custom_headers_json = '{"X-A": "b"}'
    cfg.asr.language = "zh"
    cfg.vad.speech_threshold = 0.35

    path = tmp_path / "written.toml"
    save(cfg, path)
    assert path.is_file()

    reloaded = load(path)
    assert reloaded.general.close_action == "exit"
    assert reloaded.general.open_ui_on_startup is True
    assert reloaded.asr.api.base_url == "https://api.openai.com/v1"
    assert reloaded.asr.api.custom_headers_json == '{"X-A": "b"}'
    assert reloaded.asr.language == "zh"
    assert reloaded.vad.speech_threshold == pytest.approx(0.35)


def test_dumps_is_derivable_toml(tmp_path):
    # dumps 的内容必须能被 tomllib 解析（用 load 间接验证），且包含新字段。
    text = dumps(load(None))
    assert "close_action" in text
    assert "[asr.api]" in text
    path = tmp_path / "c.toml"
    path.write_text(text, encoding="utf-8")
    load(path)


def test_save_creates_parent_dirs(tmp_path):
    cfg = load(None)
    target = tmp_path / "nested" / "dir" / "config.toml"
    save(cfg, target)
    assert target.is_file()
