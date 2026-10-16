"""界面主题（QSS）。

一套克制的浅色主题 + 强调色，重点是把状态色（绿/蓝/黄/灰/红）在托盘、
侧边栏胶囊、模型卡片之间保持一致；不追求花哨。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

ACCENT_DEFAULT = "#1f6feb"
ACCENT_OK = "#2ea043"
ACCENT_WARN = "#ca8a04"
ACCENT_ERROR = "#cf222e"
ACCENT_MUTED = "#6e7781"

QSS = """
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
    color: #1f2328;
}
QMainWindow, QWidget#centralWidget {
    background: #f6f7f9;
}
QWidget#sidebar {
    background: #ffffff;
    border-right: 1px solid #d8dee4;
}
QLabel#appTitle {
    font-size: 16px;
    font-weight: 600;
}
QLabel#statusPill {
    color: #2ea043;
    padding: 2px 8px;
}
QLabel#pageTitle {
    font-size: 18px;
    font-weight: 600;
}
QLabel#hint {
    color: #6e7781;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover {
    background: #f3f4f6;
}
QPushButton:disabled {
    color: #8c959f;
    background: #f6f7f9;
}
QPushButton#primary {
    background: #1f6feb;
    border-color: #1f6feb;
    color: #ffffff;
}
QPushButton#primary:hover {
    background: #1a63d2;
}
QPushButton#nav {
    text-align: left;
    border: none;
    background: transparent;
    padding: 8px 10px;
    border-radius: 6px;
}
QPushButton#nav:hover {
    background: #f3f4f6;
}
QPushButton#nav:checked {
    background: #ddf4ff;
    color: #0969da;
    font-weight: 600;
}
QFrame#card, QFrame#cardFrame, QFrame#playerDock {
    background: #ffffff;
    border: 1px solid #d8dee4;
    border-radius: 8px;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #d8dee4;
    border-radius: 6px;
}
QTextBrowser {
    background: #ffffff;
    border: 1px solid #d8dee4;
    border-radius: 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 4px 6px;
}
QGroupBox {
    border: 1px solid #d8dee4;
    border-radius: 8px;
    margin-top: 10px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #57606a;
}
"""
