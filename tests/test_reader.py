"""日常记录读取与音频链接解析的测试（纯函数，无 Qt）。"""

from __future__ import annotations

import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from voicenote import reader


def test_list_transcript_dates(tmp_path):
    (tmp_path / "2026-10-14.md").write_text("# a", encoding="utf-8")
    (tmp_path / "2026-10-16.md").write_text("# b", encoding="utf-8")
    (tmp_path / "2026-10-15.md").write_text("# c", encoding="utf-8")
    (tmp_path / "not-a-date.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-13-40.md").write_text("x", encoding="utf-8")  # 非法日期
    (tmp_path / "subdir").mkdir()

    dates = reader.list_transcript_dates(tmp_path)
    assert dates == [date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 14)]


def test_list_transcript_dates_missing_dir(tmp_path):
    assert reader.list_transcript_dates(tmp_path / "nope") == []


def test_read_transcript_missing(tmp_path):
    assert reader.read_transcript(tmp_path / "nope.md") == ""


def test_count_records():
    text = (
        "# 2026-10-16\n\n"
        "- `09:00:00` 第一条 [▶](../audio/a.flac)\n"
        "- `09:05:00` 第二条\n"
        "普通段落不算记录\n"
    )
    assert reader.count_records(text) == 2


def test_resolve_audio_link_relative(tmp_path):
    transcript = tmp_path / "transcripts" / "2026-10-16.md"
    transcript.parent.mkdir(parents=True)
    transcript.touch()

    resolved = reader.resolve_audio_link(
        transcript, "../audio/2026-10-16/091204-120.flac"
    )
    assert resolved == (tmp_path / "audio" / "2026-10-16" / "091204-120.flac").resolve()


def test_resolve_audio_link_percent_encoded(tmp_path):
    transcript = tmp_path / "transcripts" / "2026-10-16.md"
    transcript.parent.mkdir(parents=True)
    transcript.touch()
    href = urllib.parse.quote("../audio/2026-10-16/有 空格.flac")
    resolved = reader.resolve_audio_link(transcript, href)
    assert resolved == (tmp_path / "audio" / "2026-10-16" / "有 空格.flac").resolve()


def test_resolve_audio_link_rejects_external(tmp_path):
    transcript = tmp_path / "t.md"
    transcript.touch()
    assert reader.resolve_audio_link(transcript, "https://example.com/x.flac") is None
    assert reader.resolve_audio_link(transcript, "http://example.com/x.flac") is None
    assert reader.resolve_audio_link(transcript, "#anchor") is None
    assert reader.resolve_audio_link(transcript, "") is None


def test_markdown_with_play_links_rewrites_relative_only():
    text = (
        "- `09:00:00` 说了句话 [▶](../audio/2026-10-16/a.flac)\n"
        "- `09:01:00` 外链 [▶](https://example.com/b.flac)\n"
    )
    out = reader.markdown_with_play_links(text)
    assert f"[▶ 播放]({reader.PLAY_SCHEME}:../audio/2026-10-16/a.flac)" in out
    assert "https://example.com/b.flac" in out
    # 原链接已经不存在
    assert "[▶](../audio" not in out


def test_play_href_roundtrip():
    href = "../audio/2026-10-16/有 空格.flac"
    quoted = urllib.parse.quote(href, safe="/:.-_~%")
    assert reader.play_href_path(quoted) == href


def test_body_without_audio_links():
    text = "- `09:00:00` 正文 [▶](../audio/a.flac)\n"
    body = reader.body_without_audio_links(text)
    assert "[▶]" not in body
    assert "正文" in body


def test_today_and_paths(tmp_path):
    day = date.today() - timedelta(days=1)
    path = reader.transcript_path(tmp_path, day)
    assert path.name == f"{day:%Y-%m-%d}.md"
    today = reader.today_transcript_path(tmp_path)
    assert today.name == f"{date.today():%Y-%m-%d}.md"
