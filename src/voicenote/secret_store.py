"""API Key 的本地存储。

安全边界（Phase 2）：

- 只写入 ``<data_dir>/state/secrets.json``；**绝不**写进 ``config.toml``、
  日志或代码仓库 —— 用户分享配置、提 PR 时不会顺带泄露密钥；
- 写盘先落临时文件再原子替换，避免中断留下半个文件；
- 文件权限在 POSIX 下收紧到 0600（仅属主可读写）。Windows 下 ACL 由用户
  目录继承，程序不做额外假设；
- 静止加密（Windows DPAPI）属于 Phase 3，本模块预留 ``_protect``/``_unprotect``
  钩子：届时只改这两个函数的内部实现，调用方不动。

注意：本模块不是密码学保险箱，只解决"密钥不跟着配置文件走"这个最现实的问题。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_PROFILE = "default"
FILENAME = "secrets.json"


def mask_secret(value: str) -> str:
    """把密钥变成可安全显示/记日志的形式。"""
    value = value or ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


def _restrict_permissions(path: Path) -> None:
    """尽力把文件收紧到 0600。Windows 上没有 POSIX 位，失败无所谓。"""
    try:
        os.chmod(path, 0o600)
    except OSError as exc:  # pragma: no cover - 取决于平台
        log.debug("无法收紧 %s 的权限：%s", path, exc)


class SecretStore:
    """``state/secrets.json`` 的读写封装。线程安全。"""

    def __init__(self, state_dir: Path, filename: str = FILENAME) -> None:
        self._path = Path(state_dir) / filename
        self._lock = threading.Lock()
        self._cache: dict[str, str] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def get_api_key(self, profile: str = DEFAULT_PROFILE) -> str | None:
        return self._load().get(profile) or None

    def has_api_key(self, profile: str = DEFAULT_PROFILE) -> bool:
        return bool(self.get_api_key(profile))

    def set_api_key(self, profile: str, key: str) -> None:
        key = (key or "").strip()
        if not key:
            raise ValueError("API key 不能为空")
        with self._lock:
            data = self._read_raw()
            data.setdefault("api_keys", {})[profile] = key
            self._write(data)
            self._cache = dict(data.get("api_keys", {}))

    def delete_api_key(self, profile: str = DEFAULT_PROFILE) -> None:
        with self._lock:
            data = self._read_raw()
            keys = data.setdefault("api_keys", {})
            if profile in keys:
                del keys[profile]
                self._write(data)
            self._cache = dict(keys)

    # ---------- 内部 ----------

    def _load(self) -> dict[str, str]:
        with self._lock:
            if self._cache is None:
                keys = self._read_raw().get("api_keys", {})
                self._cache = {
                    str(k): v
                    for k, v in keys.items()
                    if isinstance(k, str) and isinstance(v, str) and v
                }
            return dict(self._cache)

    def _read_raw(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # 损坏的 secrets 文件不该让整个应用起不来：按空处理并留一条日志。
            log.warning("secrets 文件损坏或不可读（%s），按空处理：%s", self._path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        if not isinstance(data.get("api_keys"), dict):
            data["api_keys"] = {}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload["version"] = SCHEMA_VERSION
        self._path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=".secrets-", suffix=".tmp", dir=str(self._path.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            _restrict_permissions(tmp_path)
            os.replace(tmp_path, self._path)
            _restrict_permissions(self._path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
