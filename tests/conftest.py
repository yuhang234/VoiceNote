"""pytest 全局设置：无头环境下让 Qt 走 offscreen 平台插件。"""

from __future__ import annotations

import os

# 必须在任何 PySide6 导入之前设置。Windows 开发机上不受影响（有真实桌面），
# Linux/CI 上则能构造 QApplication 而无需 X11/Wayland。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
