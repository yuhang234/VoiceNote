"""OpenAI 兼容云端 ASR 引擎的测试。

两层验证：
1. 纯函数层 —— 响应路径提取、multipart 编码、错误映射、请求头占位符；
2. 真实 HTTP 层 —— 起一个本地 http.server，用真实 socket 跑完整的
   请求 → 响应 → 解析链路，覆盖 OpenAI / SiliconFlow / Groq 共用的协议形态。

不依赖外网。
"""

from __future__ import annotations

import http.server
import io
import json
import re
import ssl
import threading
import time
import urllib.error

import numpy as np
import pytest
import soundfile as sf

from voicenote.asr.openai_api_engine import (
    API_KEY_PLACEHOLDER,
    API_TEMPLATES,
    AsrApiError,
    OpenAICompatibleAsrEngine,
    build_multipart,
    describe_http_error,
    encode_flac,
    endpoint_url,
    extract_text,
    parse_custom_headers,
)
from voicenote.asr.openai_api_engine import test_connection as connection_probe
from voicenote.config import ApiConfig, AsrConfig


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def test_extract_text_variants():
    assert extract_text({"text": " 你好 "}, "text") == "你好"
    assert extract_text({"results": [{"transcript": "abc"}]}, "results[0].transcript") == "abc"
    assert extract_text({"output": {"text": "hi"}}, "$.output.text") == "hi"
    assert extract_text({"segments": [{"text": "a"}, {"text": "b"}]}, "segments") == "a b"
    assert extract_text({"sentence": ["x", "y"]}, "sentence") == "x y"
    assert extract_text({"text": None}, "text") == ""


@pytest.mark.parametrize(
    "payload,path",
    [
        ({}, "text"),
        ({"a": 1}, "b"),
        ({"items": []}, "items[0]"),
        ({"items": [1]}, "items[2]"),
        ({"a": {"b": 1}}, "a.b.c"),
    ],
)
def test_extract_text_missing_raises_empty(payload, path):
    with pytest.raises(AsrApiError) as excinfo:
        extract_text(payload, path)
    assert excinfo.value.kind == "empty"


def _parse_multipart(body: bytes, boundary: str) -> dict[str, bytes]:
    """极简 multipart 解析：返回 name → 内容。"""
    parts: dict[str, bytes] = {}
    delimiter = b"--" + boundary.encode()
    for chunk in body.split(delimiter):
        head, sep, content = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        match = re.search(rb'name="([^"]+)"', head)
        if match is None:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]
        parts[match.group(1).decode()] = content
    return parts


def test_build_multipart_fields_and_files():
    body = build_multipart(
        {"model": "whisper-1"},
        {"file": ("audio.flac", b"fLaCdata", "audio/flac")},
        "BOUNDARY123",
    )
    parts = _parse_multipart(body, "BOUNDARY123")
    assert parts["model"] == b"whisper-1"
    assert parts["file"] == b"fLaCdata"
    assert body.endswith(b"--BOUNDARY123--\r\n")


def test_parse_custom_headers_placeholder():
    headers = parse_custom_headers(
        json.dumps({"X-Api-Key": API_KEY_PLACEHOLDER, "X-Other": "v"}), "sk-real"
    )
    assert headers == {"X-Api-Key": "sk-real", "X-Other": "v"}


def test_parse_custom_headers_invalid():
    with pytest.raises(AsrApiError):
        parse_custom_headers("not json", "sk")
    with pytest.raises(AsrApiError):
        parse_custom_headers('["list"]', "sk")


def test_endpoint_url_join():
    assert (
        endpoint_url(ApiConfig(base_url="https://x.test/v1/"))
        == "https://x.test/v1/audio/transcriptions"
    )
    assert (
        endpoint_url(ApiConfig(base_url="https://x.test/v1", endpoint_path="asr"))
        == "https://x.test/v1/asr"
    )


def test_encode_flac_roundtrip():
    audio = (np.sin(np.linspace(0, 100, 1600)) * 0.1).astype(np.float32)
    data = encode_flac(audio, 16_000)
    assert data[:4] == b"fLaC"
    decoded, rate = sf.read(io.BytesIO(data), dtype="float32")
    assert rate == 16_000
    assert decoded.shape[0] == audio.shape[0]


def _http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    body = json.dumps(payload).encode()
    return urllib.error.HTTPError(
        "https://x.test", code, "err", {}, io.BytesIO(body)  # type: ignore[arg-type]
    )


def test_describe_http_error_mapping():
    exc = describe_http_error(_http_error(401, {"error": {"message": "bad key"}}))
    assert exc.kind == "auth" and exc.status == 401 and "bad key" in str(exc)

    assert describe_http_error(_http_error(429, {})).kind == "rate_limit"
    assert describe_http_error(_http_error(400, {})).kind == "http"
    assert describe_http_error(_http_error(503, {"detail": "busy"})).kind == "http"


def test_templates_registry():
    by_id = {tpl.id: tpl for tpl in API_TEMPLATES}
    for expected in ("openai", "siliconflow", "groq", "dashscope"):
        assert expected in by_id
    assert by_id["dashscope"].supported is False
    assert by_id["siliconflow"].supported is True


# ---------------------------------------------------------------------------
# 本地 HTTP 服务器集成
# ---------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server 接口
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            }
        )
        status, payload = self.server.responder(body)  # type: ignore[attr-defined]
        if isinstance(payload, bytes):
            data = payload
        else:
            data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 让测试输出干净
        return


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, responder):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.responder = responder
        self.requests: list[dict] = []


@pytest.fixture()
def api_server():
    servers: list[_Server] = []

    def make(responder=None):
        if responder is None:
            responder = lambda body: (200, {"text": "你好世界"})  # noqa: E731
        srv = _Server(responder)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv

    yield make

    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _cfg(base_url: str, **api_kwargs) -> AsrConfig:
    return AsrConfig(engine="api", api=ApiConfig(base_url=base_url, **api_kwargs))


def _audio(seconds: float = 0.2) -> np.ndarray:
    n = int(16_000 * seconds)
    return (0.05 * np.sin(np.linspace(0, 50, n))).astype(np.float32)


def test_engine_end_to_end_request_shape(api_server):
    srv = api_server()
    port = srv.server_address[1]
    cfg = _cfg(f"http://127.0.0.1:{port}/v1", model="whisper-1")
    engine = OpenAICompatibleAsrEngine(cfg, "sk-test-123")

    text = engine.transcribe(_audio(), 16_000)
    assert text == "你好世界"

    assert len(srv.requests) == 1
    request = srv.requests[0]
    assert request["path"] == "/v1/audio/transcriptions"
    assert request["headers"]["authorization"] == "Bearer sk-test-123"
    assert request["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    body = request["body"]
    assert b'name="model"' in body and b"whisper-1" in body
    assert b'name="file"' in body and b"audio.flac" in body
    assert b"fLaC" in body  # 真正的 FLAC 字节流
    assert engine.name == "api/whisper-1"


def test_engine_custom_headers_and_language(api_server):
    srv = api_server()
    port = srv.server_address[1]
    cfg = _cfg(
        f"http://127.0.0.1:{port}/v1",
        custom_headers_json=json.dumps({"X-Custom-Key": API_KEY_PLACEHOLDER}),
    )
    cfg.language = "zh"
    engine = OpenAICompatibleAsrEngine(cfg, "sk-abc")

    engine.transcribe(_audio(), 16_000)
    request = srv.requests[0]
    assert request["headers"]["x-custom-key"] == "sk-abc"
    assert b'name="language"' in request["body"] and b"zh" in request["body"]


def test_engine_empty_audio_no_request(api_server):
    srv = api_server()
    port = srv.server_address[1]
    engine = OpenAICompatibleAsrEngine(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-x")
    assert engine.transcribe(np.zeros(0, dtype=np.float32), 16_000) == ""
    assert srv.requests == []


def test_engine_requires_key(api_server):
    srv = api_server()
    port = srv.server_address[1]
    with pytest.raises(ValueError):
        OpenAICompatibleAsrEngine(_cfg(f"http://127.0.0.1:{port}/v1"), "  ")


@pytest.mark.parametrize(
    "status,payload,kind",
    [
        (401, {"error": {"message": "invalid api key"}}, "auth"),
        (403, {"message": "forbidden"}, "auth"),
        (429, {"error": "rate limited"}, "rate_limit"),
        (500, {"error": "boom"}, "http"),
    ],
)
def test_engine_http_errors(api_server, status, payload, kind):
    srv = api_server(lambda body: (status, payload))
    port = srv.server_address[1]
    engine = OpenAICompatibleAsrEngine(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-x")
    with pytest.raises(AsrApiError) as excinfo:
        engine.transcribe(_audio(), 16_000)
    assert excinfo.value.kind == kind
    assert excinfo.value.status == status


def test_engine_bad_json(api_server):
    srv = api_server(lambda body: (200, b"<html>not json</html>"))
    port = srv.server_address[1]
    engine = OpenAICompatibleAsrEngine(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-x")
    with pytest.raises(AsrApiError) as excinfo:
        engine.transcribe(_audio(), 16_000)
    assert excinfo.value.kind == "parse"


def test_engine_missing_text_field(api_server):
    srv = api_server(lambda body: (200, {"result": "x"}))
    port = srv.server_address[1]
    engine = OpenAICompatibleAsrEngine(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-x")
    with pytest.raises(AsrApiError) as excinfo:
        engine.transcribe(_audio(), 16_000)
    assert excinfo.value.kind == "empty"


def test_engine_response_path_parsing(api_server):
    srv = api_server(lambda body: (200, {"results": [{"transcript": "逐段文本"}]}))
    port = srv.server_address[1]
    cfg = _cfg(
        f"http://127.0.0.1:{port}/v1",
        response_text_path="results[0].transcript",
    )
    engine = OpenAICompatibleAsrEngine(cfg, "sk-x")
    assert engine.transcribe(_audio(), 16_000) == "逐段文本"


def test_engine_transport_errors():
    """传输层异常映射。用注入的 opener 模拟，避免依赖真实端口/网络。"""

    def raising(exc: BaseException):
        def opener(request, timeout=None):  # pragma: no cover - 只负责抛异常
            raise exc

        return opener

    cases: list[tuple[BaseException, str]] = [
        (urllib.error.URLError(ConnectionRefusedError("refused")), "connection"),
        (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionResetError("reset by peer"), "connection"),
        (ssl.SSLError("bad handshake"), "connection"),
        (OSError("network down"), "connection"),
    ]
    cfg = _cfg("http://127.0.0.1:1/v1")
    for exc, kind in cases:
        engine = OpenAICompatibleAsrEngine(cfg, "sk-x", opener=raising(exc))
        with pytest.raises(AsrApiError) as excinfo:
            engine.transcribe(_audio(), 16_000)
        assert excinfo.value.kind == kind, f"{type(exc).__name__} 映射成了 {excinfo.value.kind}"


def test_engine_timeout(api_server):
    def slow(body):
        time.sleep(2.0)
        return 200, {"text": "too late"}

    srv = api_server(slow)
    port = srv.server_address[1]
    engine = OpenAICompatibleAsrEngine(
        _cfg(f"http://127.0.0.1:{port}/v1", timeout_s=1), "sk-x"
    )
    with pytest.raises(AsrApiError) as excinfo:
        engine.transcribe(_audio(), 16_000)
    assert excinfo.value.kind == "timeout"


# ---------------------------------------------------------------------------
# 连通性测试
# ---------------------------------------------------------------------------


def test_connection_ok(api_server):
    srv = api_server(lambda body: (200, {"text": "hello"}))
    port = srv.server_address[1]
    cfg = _cfg(f"http://127.0.0.1:{port}/v1")
    result = connection_probe(cfg, "sk-x", sample=_audio())
    assert result.ok is True
    assert result.kind == "ok"
    assert "hello" in result.message


def test_connection_empty_text(api_server):
    # 字段存在但文本为空：算连通成功，提示核对提取字段
    srv = api_server(lambda body: (200, {"text": ""}))
    port = srv.server_address[1]
    result = connection_probe(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-x", sample=_audio())
    assert result.ok is True
    assert result.kind == "empty"

    # 字段根本不存在：同样是 empty 类错误，但不应表现为“网络失败”
    srv2 = api_server(lambda body: (200, {}))
    port2 = srv2.server_address[1]
    cfg2 = _cfg(f"http://127.0.0.1:{port2}/v1", response_text_path="missing_field")
    result2 = connection_probe(cfg2, "sk-x", sample=_audio())
    assert result2.ok is False
    assert result2.kind == "empty"


def test_connection_no_key():
    result = connection_probe(_cfg("http://127.0.0.1:1/v1"), "  ", sample=_audio())
    assert result.ok is False
    assert result.kind == "no_key"


def test_connection_auth_error(api_server):
    srv = api_server(lambda body: (401, {"error": "bad key"}))
    port = srv.server_address[1]
    result = connection_probe(_cfg(f"http://127.0.0.1:{port}/v1"), "sk-bad", sample=_audio())
    assert result.ok is False
    assert result.kind == "auth"


def test_connection_factory_exception():
    def broken_factory(cfg, key):
        raise AsrApiError("connection", "无法连接 Base URL")

    result = connection_probe(
        _cfg("http://127.0.0.1:1/v1"), "sk-x", sample=_audio(), engine_factory=broken_factory
    )
    assert result.ok is False
    assert result.kind == "connection"


def test_connection_factory_generic_exception():
    def broken_factory(cfg, key):
        raise RuntimeError("unexpected")

    result = connection_probe(
        _cfg("http://127.0.0.1:1/v1"), "sk-x", sample=_audio(), engine_factory=broken_factory
    )
    assert result.ok is False
    assert "unexpected" in result.message
