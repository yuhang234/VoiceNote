"""冻结点（PyInstaller 打包后）与源码运行时的路径解析。

打包后这三个东西的含义全变了：

- ``sys.prefix`` 不再是 venv，而是 PyInstaller 的运行时目录
- ``__file__`` 指向包内部的副本，据此往上推"项目根目录"是错的
- ``sys.executable`` 是 VoiceNote.exe，不再是 python.exe

凡是依赖它们的地方都必须走这里。否则打包版会以**很难排查**的方式失效 ——
比如 CUDA DLL 找不到会导致 GPU 静默回落到 CPU，慢十倍但表面上一切正常。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的产物里。"""
    return getattr(sys, "frozen", False)


def bundle_root() -> Path:
    """返回到能放资源的根目录。

    冻结时是 PyInstaller 的解包根（onedir 模式下即 ``_internal`` 目录），
    非冻结时是当前 venv 的 ``site-packages``。
    """
    if is_frozen():
        # onedir 与 onefile 都会设置 _MEIPASS
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(sys.prefix) / "Lib" / "site-packages"


def project_root() -> Path | None:
    """源码树的根目录。冻结之后没有这个概念，返回 None。"""
    if is_frozen():
        return None
    return Path(__file__).resolve().parents[2]


def executable_path() -> Path:
    """用于开机自启的可执行文件。

    冻结时就是 VoiceNote.exe；否则优先 pythonw.exe（无控制台子系统，开机不闪黑窗）。
    """
    exe = Path(sys.executable)
    if is_frozen():
        return exe

    pythonw = exe.with_name("pythonw.exe")
    return pythonw if pythonw.is_file() else exe


def open_in_default_app(path: Path) -> None:
    """用系统默认程序打开文件或目录。

    Windows 用 ``os.startfile``（打包版也走这里）；macOS 用 ``open``；
    其余平台（开发机 / CI）用 ``xdg-open``。非 Windows 平台没有这些命令时
    会抛 ``OSError``，由调用方决定提示方式。
    """
    path = Path(path)
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        return

    import subprocess

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

