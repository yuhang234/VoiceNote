"""界面层烟雾测试（Qt offscreen 平台）。

只验证“接线”是否正确，不追求像素级 UI 测试：
- 关闭主窗口 = 隐藏到托盘（close_action=minimize_to_tray），退出行为可切换；
- 托盘菜单项（打开主界面 / 选项 / API / 退出）正确调用控制器；
- 阅读器把 [▶] 链接解析成本地音频路径并交给播放器；
- API 配置页模板填充与密钥写入走 SecretStore（不写进 config）。

没有 PySide6 的环境直接跳过，不阻塞核心逻辑测试。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("PySide6")

from voicenote.app import Application  # noqa: E402
from voicenote.config import load  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from voicenote.ui.app_window import ensure_qt_app

    return ensure_qt_app([])


@pytest.fixture()
def app_env(tmp_path, qapp):
    cfg = load(None)
    cfg.general.data_dir = str(tmp_path / "data")

    def factory(asr_cfg, *, api_key=None):
        class Engine:
            name = f"fake/{asr_cfg.engine}"

            def warmup(self) -> None:
                pass

            def transcribe(self, audio, sample_rate) -> str:
                return ""

        return Engine()

    application = Application(
        cfg, config_path=tmp_path / "config.toml", engine_factory=factory
    )
    application.notify = lambda message: None  # 测试里不弹真实气泡
    return application, cfg, tmp_path


# ---------------------------------------------------------------------------
# 主窗口生命周期
# ---------------------------------------------------------------------------


def test_window_close_hides_to_tray(app_env):
    from voicenote.ui.app_window import MainWindow

    application, cfg, _ = app_env
    window = MainWindow(application)
    window.show()
    assert window.isVisible()

    window.close()
    assert not window.isVisible()  # 隐藏而不是销毁
    assert window.isHidden()
    assert cfg.general.close_action == "minimize_to_tray"


def test_window_close_exit_calls_shutdown(app_env):
    from voicenote.ui.app_window import MainWindow

    application, cfg, _ = app_env
    cfg.general.close_action = "exit"
    calls: list[int] = []
    application.shutdown = lambda: calls.append(1)

    window = MainWindow(application)
    window.show()
    window.close()
    assert calls == [1]


def test_show_page_switches_stack(app_env):
    from voicenote.ui.app_window import MainWindow, PAGES

    application, cfg, _ = app_env
    window = MainWindow(application)
    for expected_index, page in enumerate(PAGES):
        window.show_page(page)
        assert window._stack.currentIndex() == expected_index


def test_window_state_pill_updates(app_env):
    from voicenote.status import IconState
    from voicenote.ui.app_window import MainWindow

    application, cfg, _ = app_env
    window = MainWindow(application)
    window.on_state_changed(IconState.PAUSED)
    assert "暂停" in window._status_pill.text()
    # 按钮文案跟随控制器的真实暂停状态，而不是任意传入的 state
    assert "暂停监听" in window._btn_quick_pause.text()

    application.pause()
    window.on_state_changed(application.state)
    assert "暂停" in window._status_pill.text()
    assert "恢复" in window._btn_quick_pause.text()

    application.resume()
    window.on_state_changed(application.state)
    assert "监听" in window._status_pill.text()
    assert "暂停监听" in window._btn_quick_pause.text()


# ---------------------------------------------------------------------------
# 托盘
# ---------------------------------------------------------------------------


def test_tray_menu_actions_route_to_controller(app_env):
    from voicenote.ui.tray_icon import TrayIcon

    application, cfg, _ = app_env
    pages: list[str] = []
    application.show_page = lambda page: pages.append(page)

    tray = TrayIcon(application)
    actions = {action.text(): action for action in tray._menu.actions()}

    actions["📝 打开主界面"].trigger()
    actions["⚙️ 选项设置…"].trigger()
    actions["🔑 API 配置…"].trigger()
    assert pages == ["transcripts", "models", "api"]


def test_tray_pause_and_quit(app_env):
    from voicenote.ui.tray_icon import TrayIcon

    application, cfg, _ = app_env
    quits: list[int] = []
    application.shutdown = lambda: quits.append(1)

    tray = TrayIcon(application)
    actions = {action.text(): action for action in tray._menu.actions()}

    pause_action = tray._pause_action
    pause_action.trigger()
    assert application.paused is True
    assert "恢复" in pause_action.text()

    pause_action.trigger()
    assert application.paused is False

    actions["❌ 退出 VoiceNote"].trigger()
    assert quits == [1]


def test_tray_autostart_on_non_windows_is_explained(app_env):
    from voicenote.ui.tray_icon import TrayIcon

    application, cfg, _ = app_env
    messages: list[str] = []
    application.notify = lambda message: messages.append(message)

    tray = TrayIcon(application)
    tray._on_toggle_autostart()
    # Linux/macOS 上会走 ImportError 分支；Windows 上这条断言不适用
    import sys

    if not sys.platform.startswith("win"):
        assert any("Windows" in message for message in messages)


# ---------------------------------------------------------------------------
# 阅读器
# ---------------------------------------------------------------------------


def _make_transcripts(root: Path):
    """造一份与 store.py 输出同构的记录 + 一段真实 FLAC。"""
    day = date.today()
    transcripts = root / "transcripts"
    audio_dir = root / "audio" / f"{day:%Y-%m-%d}"
    transcripts.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_path = audio_dir / "093000-000.flac"
    sf.write(audio_path, np.zeros(1_600, dtype=np.float32), 16_000, format="FLAC")

    md_path = transcripts / f"{day:%Y-%m-%d}.md"
    md_path.write_text(
        f"# {day:%Y-%m-%d}\n\n"
        f"- `09:30:00` 今天要测试阅读器。 "
        f"[▶](../audio/{day:%Y-%m-%d}/093000-000.flac)\n",
        encoding="utf-8",
    )
    return md_path, audio_path


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[Path] = []

    def play(self, path) -> None:
        self.played.append(Path(path))

    def stop(self) -> None:
        pass

    def seek(self, position_ms: int) -> None:
        pass

    def toggle_pause(self) -> None:
        pass


def test_reader_lists_today(app_env):
    from voicenote.ui.reader_view import TranscriptsView

    application, cfg, tmp_path = app_env
    _make_transcripts(cfg.data_dir)

    view = TranscriptsView(application)
    assert view._date_list.count() == 1
    assert "今日" in view._date_list.item(0).text()
    assert "播放" in view._browser.toPlainText()
    assert "1 条记录" in view._stats_label.text()


def test_reader_play_link_resolves_audio(app_env):
    from voicenote.ui.reader_view import TranscriptsView

    application, cfg, tmp_path = app_env
    md_path, audio_path = _make_transcripts(cfg.data_dir)

    view = TranscriptsView(application)
    view._player = FakePlayer()

    rel = f"../audio/{date.today():%Y-%m-%d}/{audio_path.name}"
    view._play_from_href(rel)
    assert view._player.played == [audio_path.resolve()]
    assert not view._player_dock.isHidden()  # 播放条出现（父窗口未 show，故看 isHidden）


def test_reader_missing_audio_notifies(app_env):
    from voicenote.ui.reader_view import TranscriptsView

    application, cfg, tmp_path = app_env
    _make_transcripts(cfg.data_dir)
    messages: list[str] = []
    application.notify = lambda message: messages.append(message)

    view = TranscriptsView(application)
    view._player = FakePlayer()
    view._play_from_href("../audio/2026-10-16/does-not-exist.flac")
    assert messages and "不存在" in messages[0]
    assert view._player.played == []


def test_reader_copy_strips_audio_markers(app_env, qapp):
    from voicenote.ui.reader_view import TranscriptsView

    application, cfg, tmp_path = app_env
    _make_transcripts(cfg.data_dir)

    view = TranscriptsView(application)
    view._on_copy()
    text = qapp.clipboard().text()
    assert "今天要测试阅读器" in text
    assert "[▶]" not in text


# ---------------------------------------------------------------------------
# API 配置页
# ---------------------------------------------------------------------------


def test_api_view_template_fill(app_env):
    from voicenote.ui.api_config_view import ApiConfigView

    application, cfg, _ = app_env
    view = ApiConfigView(application)

    index = view._combo_template.findData("groq")
    view._combo_template.setCurrentIndex(index)
    view._on_apply_template()

    assert view._edit_base_url.text() == "https://api.groq.com/openai/v1"
    assert view._edit_model.text() == "whisper-large-v3-turbo"
    api = view._collect_api()
    assert api.template == "groq"


def test_api_view_save_stores_key_in_secrets_not_config(app_env):
    from voicenote.ui.api_config_view import ApiConfigView

    application, cfg, _ = app_env
    view = ApiConfigView(application)
    view._edit_key.setText("sk-ui-test-key")
    view._radio_local.setChecked(True)  # 仍用本地引擎 → 只保存 API 配置

    view._on_save()

    assert application.secrets.get_api_key() == "sk-ui-test-key"
    config_text = (application.config_path).read_text(encoding="utf-8")
    assert "sk-ui-test-key" not in config_text
    # 密钥输入框清空并提示“已保存”
    assert view._edit_key.text() == ""
    assert "已保存" in view._edit_key.placeholderText()


def test_api_view_dashscope_marked_unsupported(app_env):
    from voicenote.ui.api_config_view import ApiConfigView

    application, cfg, _ = app_env
    view = ApiConfigView(application)
    index = view._combo_template.findData("dashscope")
    view._combo_template.setCurrentIndex(index)
    view._on_apply_template()
    assert "暂不可用" in view._template_note.text() or "未实现" in view._template_note.text()


# ---------------------------------------------------------------------------
# 托盘通知与界面装配回归测试
# ---------------------------------------------------------------------------


def test_tray_menu_uses_theme_aware_stylesheet(qapp, monkeypatch):
    from voicenote.ui.tray_icon import TrayIcon, _MENU_QSS_DARK, _MENU_QSS_LIGHT

    class DummyController:
        paused = False
        active_engine_name = "faster-whisper/large-v3-turbo"

        def show_page(self, page):  # noqa: ARG002
            pass

        def open_data_dir(self):
            pass

        def shutdown(self):
            pass

        def notify(self, message, title=None):  # noqa: ARG002
            pass

    tray = TrayIcon(DummyController())
    expected = _MENU_QSS_DARK if TrayIcon._is_dark_mode() else _MENU_QSS_LIGHT
    assert tray._menu.styleSheet() == expected

    # 两套主题都必须明确设置前景色、背景色和选中态，避免系统原生配色干扰。
    assert "color: #e8e8e8" in _MENU_QSS_DARK
    assert "background: #2d2d2d" in _MENU_QSS_DARK
    assert "color: #1f2328" in _MENU_QSS_LIGHT
    assert "background: #ffffff" in _MENU_QSS_LIGHT

    monkeypatch.setattr(tray, "_is_dark_mode", lambda: True)
    tray._apply_menu_theme()
    assert tray._menu.styleSheet() == _MENU_QSS_DARK

    monkeypatch.setattr(tray, "_is_dark_mode", lambda: False)
    tray._apply_menu_theme()
    assert tray._menu.styleSheet() == _MENU_QSS_LIGHT


def test_tray_icon_notify(qapp):
    from voicenote.ui.tray_icon import TrayIcon

    class DummyController:
        paused = False
        active_engine_name = "test"
        def show_page(self, page): pass
        def open_data_dir(self): pass
        def shutdown(self): pass
        def pause(self): pass
        def resume(self): pass
        def notify(self, msg): pass

    tray = TrayIcon(DummyController())
    # 验证 notify 契约：支持单个 message，以及传入自定义 title
    tray.notify("测试通知内容")
    tray.notify("第二条通知", title="自定义标题")


def test_application_init_ui_wiring(tmp_path, qapp):
    cfg = load(None)
    cfg.general.data_dir = str(tmp_path / "data")
    app = Application(cfg, config_path=tmp_path / "config.toml")
    try:
        ok = app._init_ui()
        assert ok is True
        assert hasattr(app._tray, "notify")
        # 触发通知，验证全链路接线正常（不抛 AttributeError）
        app.notify("全链路接线测试通知")
    finally:
        app._teardown_ui()


def test_packaging_spec_modules():
    spec_path = Path(__file__).resolve().parents[1] / "packaging" / "voicenote.spec"
    assert spec_path.is_file()
    content = spec_path.read_text(encoding="utf-8")
    assert "PySide6.QtWidgets" in content
    assert "voicenote.ui" in content
    assert "pystray" in content  # in excludes
