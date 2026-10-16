"""VoiceNote 图形界面（PySide6）。

只在这里导入 Qt —— ``voicenote`` 的核心逻辑（配置、VAD、落盘、ASR 引擎）
全部与 Qt 解耦，可以在无图形环境的机器上测试。

页面结构：

    MainWindow（侧边栏 + QStackedWidget）
    ├── TranscriptsView    日常记录 Markdown 阅读器 + 内嵌音频播放
    ├── LocalModelsView    本地模型下载 / 清理 / 一键切换
    ├── ApiConfigView      云端 OpenAI 兼容 API 配置与连通性测试
    └── GeneralSettingsView 录音、VAD、开机自启等系统设置

    TrayIcon               QSystemTrayIcon 原生托盘（替代旧 pystray）
"""
