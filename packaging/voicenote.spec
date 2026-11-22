# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

用法（一般通过 scripts/build.ps1 调用）：
    .venv\\Scripts\\pyinstaller.exe --noconfirm packaging\\voicenote.spec

两个关键决定：

**为什么是 onedir 而不是 onefile。** 本项目依赖树在 1.4GB 左右，onefile 每次启动都要
把它整个解压到临时目录，对一个常驻后台的应用是灾难性的。onedir 只在安装时解压一次。

**为什么 datas 里要手写这么一大串。** 下面这些原生依赖都是运行时通过
``os.add_dll_directory`` / ctypes 动态加载的，PyInstaller 的静态分析完全看不见它们。
漏掉通常不会立刻报错 —— 只是 GPU 悄悄用不了、慢十倍，极难排查。所以显式列出来。

**为什么 nvidia 只挑 ``*.dll``。** ``nvidia-cudnn-cu12`` 与 ``nvidia-cublas-cu12`` 的 wheel
里除了运行时要用的 DLL，还带着给**编译 cuDNN/cuBLAS 的扩展**用的静态库与 C++ 头文件
（合计约 1.5GB）—— 本项目既不编译也不链接它们，纯属白带。所以显式过滤，只留
``nvidia/<pkg>/bin`` 下的 DLL。运行期行为与整包复制完全相同：``cuda_env.register_cuda_dlls``
本来也只会把 ``nvidia/*/bin`` 加进 DLL 搜索路径。
"""

import sys
from pathlib import Path

SITE = Path(sys.prefix) / "Lib" / "site-packages"
# SPECPATH 是本文件所在目录（packaging/），往上一层就是项目根
ROOT = Path(SPECPATH).parent


def _cuda_dlls() -> list:
    """只收集 GPU 推理真正要用的 CUDA DLL。

    保留每个 nvidia 包的 ``bin/`` 目录结构（cuda_env 按 ``nvidia/<pkg>/bin`` 找），
    丢掉 wheel 里的 ``lib/``（静态库）、``include/``（头文件）、``doc/``（文档）。
    缺任何一个必需的 DLL 就直接抛错：打包阶段漏包必须变成构建失败，
    不能变成用户装完才发现 GPU 静默降级。
    """
    required = {
        "nvidia/cudnn/bin/cudnn64_9.dll",
        "nvidia/cublas/bin/cublas64_12.dll",
    }
    nvidia = SITE / "nvidia"
    picked: list = []
    found = set()
    if nvidia.is_dir():
        for pkg in sorted(nvidia.iterdir()):
            bin_dir = pkg / "bin"
            if not bin_dir.is_dir():
                continue
            for dll in sorted(bin_dir.glob("*.dll")):
                rel = str(dll.relative_to(SITE)).replace("\\", "/")
                picked.append((str(dll), rel))
                found.add(rel)
    missing = required - found
    if missing:
        raise SystemExit(
            "voicenote.spec: 找不到必需的 CUDA DLL：" + ", ".join(sorted(missing))
            + "\n  先确认 .venv 里装了 nvidia-cudnn-cu12 与 nvidia-cublas-cu12"
        )
    return picked


datas = [
    # ---- 原生依赖：分析不到，必须显式打包 ----
    *_cuda_dlls(),                                       # cuDNN/cuBLAS 运行时 DLL，GPU 必需
    (SITE / "ctranslate2", "ctranslate2"),                # ct2 自带的 ctranslate2.dll 等
    (SITE / "onnxruntime" / "capi", "onnxruntime/capi"),   # VAD 用的 ORT 运行时
    (SITE / "_sounddevice_data", "_sounddevice_data"),     # PortAudio（麦克风）
    (SITE / "_soundfile_data", "_soundfile_data"),         # libsndfile（写 FLAC）
    # ---- 便携版里顺手带上说明文件 ----
    (ROOT / "README.md", "."),
    (ROOT / "LICENSE", "."),
    # 自检用的样例音频。带在包里，打包版自检就不依赖网络 ——
    # 否则网络一抖，就分不清是打包坏了还是网断了。
    (ROOT / "packaging" / "selftest_sample.flac", "."),
]

hiddenimports = [
    "onnxruntime.capi._pybind_state",
    # PySide6 GUI 核心与 voicenote.ui 模块（延迟加载 / 运行时导入）
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "voicenote.ui",
    "voicenote.ui.app_window",
    "voicenote.ui.tray_icon",
    "voicenote.ui.general_view",
    "voicenote.ui.api_config_view",
    "voicenote.ui.local_models_view",
    "voicenote.ui.reader_view",
    "voicenote.ui.player",
    "voicenote.ui.styles",
    "voicenote.ui.bridge",
    "voicenote.ui.workers",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 这些都没用到，排掉能省体积也少些意外
    excludes=[
        "pystray",
        "tkinter",
        "pytest",
        "_pytest",
        "matplotlib",
        "scipy",
        "IPython",
        "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceNote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 不用 UPX：压缩收益有限，而且加壳的 exe 极易被杀软误报
    upx=False,
    # 无控制台子系统 —— 托盘应用不该弹黑窗
    console=False,
    icon=str(ROOT / "packaging" / "voicenote.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VoiceNote",
)
