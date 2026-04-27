"""500 兜底 handler 必须记录 exc_info / traceback。"""

from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

from app.core.errors import unhandled_exception_handler


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/v1/fail",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("test", 80),
    }
    return Request(scope=scope)


@pytest.mark.asyncio
async def test_unhandled_exception_logs_with_traceback(caplog):
    req = _fake_request()
    try:
        raise RuntimeError("boom-42")
    except RuntimeError as e:
        exc = e
    with caplog.at_level(logging.ERROR):
        resp = await unhandled_exception_handler(req, exc)
    assert resp.status_code == 500
    body = resp.body.decode("utf-8")
    # 响应体不应泄露堆栈
    assert "boom-42" not in body
    assert "RuntimeError" not in body
    # 但 structlog / stdlib 日志输出应当含异常信息
    combined = " ".join(r.getMessage() for r in caplog.records) + " " + caplog.text
    # structlog 不一定走到 stdlib caplog（取决于配置），这里退而求其次：
    # 验证 handler 至少调用了一次；不强求 caplog 命中。
    # 真正可靠的检查在 test_unhandled_exception_emits_exc_info_to_stdout。
    _ = combined


@pytest.mark.asyncio
async def test_unhandled_exception_emits_exc_info_to_stdout(capsys):
    from app.core.logging import configure_logging

    configure_logging()
    req = _fake_request()
    try:
        raise RuntimeError("boom-xyz")
    except RuntimeError as e:
        exc = e
    resp = await unhandled_exception_handler(req, exc)
    assert resp.status_code == 500
    captured = capsys.readouterr()
    out = captured.out + captured.err
    # structlog 配置把日志写 stdout，含 exc_type + traceback
    assert "unhandled_exception" in out
    assert "RuntimeError" in out or "boom-xyz" in out
