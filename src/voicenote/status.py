"""应用状态枚举：托盘图标颜色、标题、界面状态胶囊共用同一份定义。

独立成模块是为了让 ``app.py``（可能在无 Qt 环境下被测试）与
``ui/tray_icon.py`` 都能引用，而不把 Qt 依赖带进核心逻辑。
"""

from __future__ import annotations

from enum import Enum


class IconState(Enum):
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    LOADING = "loading"
    PAUSED = "paused"
    ERROR = "error"


#: 图标圆的 RGB 颜色。
COLORS: dict[IconState, tuple[int, int, int]] = {
    IconState.LISTENING: (46, 160, 67),
    IconState.TRANSCRIBING: (31, 111, 235),
    IconState.LOADING: (202, 138, 4),
    IconState.PAUSED: (130, 130, 130),
    IconState.ERROR: (207, 34, 46),
}

TITLES: dict[IconState, str] = {
    IconState.LISTENING: "VoiceNote — 监听中",
    IconState.TRANSCRIBING: "VoiceNote — 识别中",
    IconState.LOADING: "VoiceNote — 正在准备模型",
    IconState.PAUSED: "VoiceNote — 已暂停",
    IconState.ERROR: "VoiceNote — 出错了",
}

#: 界面状态胶囊的文案。
LABELS: dict[IconState, str] = {
    IconState.LISTENING: "● 监听中",
    IconState.TRANSCRIBING: "● 识别中",
    IconState.LOADING: "● 正在准备模型",
    IconState.PAUSED: "● 已暂停",
    IconState.ERROR: "● 出错",
}
