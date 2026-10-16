"""日常记录（transcripts）的读取与音频链接解析。

刻意不依赖 Qt：日期列表、Markdown 文本、音频相对路径的解析都是纯函数，
可以在没有图形环境的机器上直接单测；``ui/reader_view.py`` 只负责展示。

Markdown 格式（由 ``store.py`` 写入，本模块必须保持兼容）：

    # 2026-10-16

    - `09:12:04` 正文…… [▶](../audio/2026-10-16/091204-120.flac)
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

DATE_FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
#: store.py 写出的 [▶](相对路径) 链接。
AUDIO_LINK_RE = re.compile(r"\[▶\]\((?P<href>[^)]+)\)")
#: 一条记录行：- `HH:MM:SS` 正文 [▶](...)
RECORD_LINE_RE = re.compile(
    r"^- `(?P<stamp>\d{2}:\d{2}:\d{2})` (?P<body>.*)$"
)
#: QTextBrowser 里播放链接使用的自定义 scheme。
PLAY_SCHEME = "voicenote-audio"


def list_transcript_dates(transcripts_dir: Path) -> list[date]:
    """列出所有日期记录，按日期倒序（最近的在前）。"""
    transcripts_dir = Path(transcripts_dir)
    if not transcripts_dir.is_dir():
        return []

    days: set[date] = set()
    for entry in transcripts_dir.iterdir():
        match = DATE_FILENAME_RE.match(entry.name)
        if not match or not entry.is_file():
            continue
        try:
            days.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            log.debug("忽略非法日期文件：%s", entry.name)
    return sorted(days, reverse=True)


def transcript_path(transcripts_dir: Path, day: date) -> Path:
    return Path(transcripts_dir) / f"{day:%Y-%m-%d}.md"


def today_transcript_path(transcripts_dir: Path, today: date | None = None) -> Path:
    return transcript_path(transcripts_dir, today or date.today())


def read_transcript(path: Path) -> str:
    """读取记录文本；文件不存在时返回空串。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        log.warning("读取记录失败 %s：%s", path, exc)
        return ""


def count_records(markdown_text: str) -> int:
    """统计记录条数（形如 ``- `HH:MM:SS` …`` 的行）。"""
    return sum(1 for line in markdown_text.splitlines() if RECORD_LINE_RE.match(line))


def resolve_audio_link(transcript_path_: Path, href: str) -> Path | None:
    """把 Markdown 里的相对音频链接解析成本地绝对路径。

    返回 None 表示这个链接不该由内置播放器处理（外链、空链接等）。
    """
    href = urllib.parse.unquote((href or "").strip())
    if not href:
        return None
    if href.startswith("#"):
        return None

    parsed = urllib.parse.urlparse(href)
    if parsed.scheme in ("http", "https", "mailto"):
        return None

    base_dir = Path(transcript_path_).parent
    target = (base_dir / href).resolve()
    return target


def is_playable(audio_path: Path) -> bool:
    return Path(audio_path).is_file()


def markdown_with_play_links(markdown_text: str) -> str:
    """把 ``[▶](相对路径)`` 改写成带自定义 scheme 的链接，交给 QTextBrowser 渲染。

    QTextBrowser 会把相对链接解析成奇怪的 URL，改成显式 scheme 后
    ``anchorClicked`` 拿到的路径是原文，解析逻辑全部集中在
    ``resolve_audio_link`` 一处。
    """
    def repl(match: re.Match[str]) -> str:
        href = match.group("href").strip()
        if not href or urllib.parse.urlparse(href).scheme in ("http", "https"):
            return match.group(0)
        quoted = urllib.parse.quote(href, safe="/:.-_~%")
        return f"[▶ 播放]({PLAY_SCHEME}:{quoted})"

    return AUDIO_LINK_RE.sub(repl, markdown_text)


def play_href_path(url_path: str) -> str:
    """从 ``voicenote-audio:<quoted path>`` 的 URL 里取回原始 href。"""
    return urllib.parse.unquote(url_path or "")


def body_without_audio_links(markdown_text: str) -> str:
    """去掉音频标记后的纯文本（复制到剪贴板用）。"""
    return AUDIO_LINK_RE.sub("", markdown_text)
