"""API Key 本地存储的测试。

关键约束：
- 密钥读写往返正确；
- 密钥绝不写进 config.toml（本测试显式验证一次）;
- 损坏的 secrets.json 不会让应用崩溃；
- POSIX 下文件权限收紧到 0600。
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from voicenote.config import dumps, load
from voicenote.secret_store import SecretStore, mask_secret


def test_set_get_delete_roundtrip(tmp_path):
    store = SecretStore(tmp_path / "state")
    assert store.get_api_key() is None
    assert not store.has_api_key()

    store.set_api_key("default", "sk-test-1234567890")
    assert store.get_api_key() == "sk-test-1234567890"
    assert store.has_api_key()

    # 新实例（模拟重启）同样能读到
    again = SecretStore(tmp_path / "state")
    assert again.get_api_key() == "sk-test-1234567890"

    again.delete_api_key("default")
    assert again.get_api_key() is None
    assert not again.has_api_key()


def test_multiple_profiles(tmp_path):
    store = SecretStore(tmp_path / "state")
    store.set_api_key("default", "sk-a")
    store.set_api_key("work", "sk-b")
    assert store.get_api_key("default") == "sk-a"
    assert store.get_api_key("work") == "sk-b"
    store.delete_api_key("work")
    assert store.get_api_key("default") == "sk-a"
    assert store.get_api_key("work") is None


def test_empty_key_rejected(tmp_path):
    store = SecretStore(tmp_path / "state")
    with pytest.raises(ValueError):
        store.set_api_key("default", "   ")


def test_secret_never_in_config_dump(tmp_path):
    """把密钥存进 SecretStore 后，config.toml 的输出里不能出现它。"""
    store = SecretStore(tmp_path / "state")
    store.set_api_key("default", "sk-super-secret-value")

    cfg = load(None)
    dumped = dumps(cfg)
    assert "sk-super-secret-value" not in dumped

    # 同时实际写盘验证一次
    out = tmp_path / "config.toml"
    from voicenote.config import save

    save(cfg, out)
    assert "sk-super-secret-value" not in out.read_text(encoding="utf-8")


def test_corrupt_file_treated_as_empty(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "secrets.json").write_text("{ this is not json", encoding="utf-8")
    store = SecretStore(state)
    assert store.get_api_key() is None
    # 仍然可以正常写入并覆盖坏了的内容
    store.set_api_key("default", "sk-new")
    assert store.get_api_key() == "sk-new"
    data = json.loads((state / "secrets.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["api_keys"]["default"] == "sk-new"


def test_file_permissions_posix(tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("Windows 上没有 POSIX 权限位")
    store = SecretStore(tmp_path / "state")
    store.set_api_key("default", "sk-x")
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600


def test_mask_secret():
    assert mask_secret("") == "****"
    assert mask_secret("short") == "****"
    masked = mask_secret("sk-1234567890abcdef")
    assert masked.startswith("sk-1")
    assert masked.endswith("cdef")
    assert "567890abcd" not in masked
