"""工作线程 → GUI 主线程的信号桥。

Qt 的 AutoConnection 会把跨线程 emit 自动排队到接收者所在线程执行，
所以后台线程（ASR、下载、连通性测试）可以放心地在这里发信号，
由主线程去更新托盘、窗口和阅读器。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class UiBridge(QObject):
    #: 应用状态变化（status.IconState）。
    state_changed = Signal(object)
    #: 需要弹给用户的一条托盘气泡。
    message = Signal(str)
    #: 新记录已写入当日 markdown（绝对路径），阅读器据此刷新。
    transcript_saved = Signal(str)
