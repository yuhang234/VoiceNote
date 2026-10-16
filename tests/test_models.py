"""本地模型清单、缓存判定与下载重试逻辑的测试。

下载函数把“怎么下”抽象成了可注入的 fetch，所以这些测试完全离线：
不碰 huggingface_hub、不碰网络，只验证状态机和重试/取消/校验逻辑。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from voicenote import models


def fake_weight(cache_root: Path, model_id: str, content: bytes = b"weights") -> Path:
    """在假缓存目录里放一个合法的权重文件。"""
    snap = models.model_cache_dir(model_id, cache_root) / "snapshots" / "rev1"
    snap.mkdir(parents=True, exist_ok=True)
    path = snap / "model.bin"
    path.write_bytes(content)
    return path


def test_registry_contains_expected_models():
    ids = [spec.id for spec in models.LOCAL_MODELS]
    for expected in ("tiny", "base", "small", "large-v3-turbo"):
        assert expected in ids
    sensevoice = models.model_spec("sensevoice-small")
    assert sensevoice is not None
    assert sensevoice.available is False
    assert "Phase 3" in sensevoice.unavailable_reason


def test_model_spec_unknown():
    assert models.model_spec("no-such-model") is None
    # 未知模型退回自身作为 repo 名
    assert models.resolve_repo("some/unknown-repo") == "some/unknown-repo"


def test_whisper_model_cached_true_false(tmp_path):
    assert models.whisper_model_cached("tiny", tmp_path) is False

    # 空 snapshots 目录不算缓存
    (models.model_cache_dir("tiny", tmp_path) / "snapshots" / "rev1").mkdir(parents=True)
    assert models.whisper_model_cached("tiny", tmp_path) is False

    fake_weight(tmp_path, "tiny")
    assert models.whisper_model_cached("tiny", tmp_path) is True


def test_download_success_via_injected_fetch(tmp_path):
    calls: list[str] = []
    progress_events: list[models.DownloadProgress] = []
    cancel = threading.Event()

    def fetch(spec, cache_root, cancel_event, progress):
        calls.append(spec.id)
        assert cancel_event is cancel  # 注入的取消事件原样传给 fetch
        if progress is not None:
            progress(models.DownloadProgress(spec.id, 0.5, 10, 20, 0.0))
        fake_weight(cache_root, spec.id)
        return models.model_cache_dir(spec.id, cache_root)

    result = models.download_model(
        "tiny",
        hub_cache=tmp_path,
        fetch=fetch,
        progress=progress_events.append,
        cancel=cancel,
        retry_delay_s=0,
    )
    assert result == models.model_cache_dir("tiny", tmp_path)
    assert calls == ["tiny"]
    assert progress_events and progress_events[0].model_id == "tiny"


def test_download_retry_then_success(tmp_path):
    attempts = {"n": 0}

    def flaky_fetch(spec, cache_root, cancel, progress):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("网络抖动")
        fake_weight(cache_root, spec.id)
        return models.model_cache_dir(spec.id, cache_root)

    result = models.download_model(
        "base",
        hub_cache=tmp_path,
        fetch=flaky_fetch,
        retries=2,
        retry_delay_s=0,
    )
    assert attempts["n"] == 3
    assert models.whisper_model_cached("base", tmp_path)
    assert result.name.startswith("models--")


def test_download_failure_raises_after_retries(tmp_path):
    def always_fail(spec, cache_root, cancel, progress):
        raise RuntimeError("一直失败")

    with pytest.raises(models.ModelDownloadError):
        models.download_model(
            "small",
            hub_cache=tmp_path,
            fetch=always_fail,
            retries=1,
            retry_delay_s=0,
        )


def test_download_sensevoice_unavailable(tmp_path):
    with pytest.raises(models.ModelUnavailableError):
        models.download_model("sensevoice-small", hub_cache=tmp_path, retry_delay_s=0)


def test_download_cancelled_before_start(tmp_path):
    cancel = threading.Event()
    cancel.set()

    def fetch(spec, cache_root, cancel_event, progress):  # pragma: no cover
        raise AssertionError("取消后不应该发起下载")

    with pytest.raises(models.DownloadCancelled):
        models.download_model(
            "tiny", hub_cache=tmp_path, fetch=fetch, cancel=cancel, retry_delay_s=0
        )


def test_download_skips_when_cached(tmp_path):
    fake_weight(tmp_path, "tiny")

    def fetch(spec, cache_root, cancel, progress):  # pragma: no cover
        raise AssertionError("已缓存时不应该再下载")

    result = models.download_model("tiny", hub_cache=tmp_path, fetch=fetch, retry_delay_s=0)
    assert result == models.model_cache_dir("tiny", tmp_path)


def test_size_and_delete(tmp_path):
    fake_weight(tmp_path, "tiny", content=b"x" * 100)
    assert models.model_downloaded_size("tiny", tmp_path) >= 100

    assert models.delete_model_cache("tiny", tmp_path) is True
    assert models.whisper_model_cached("tiny", tmp_path) is False
    # 再次删除返回 False
    assert models.delete_model_cache("tiny", tmp_path) is False
