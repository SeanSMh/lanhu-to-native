"""prepublish_check 规则 + _cleanup_unsupported_markdown 的纯函数测试。"""

from __future__ import annotations

from app.services.writing_service import (
    _cleanup_unsupported_markdown,
    _single_source_heavy,
)


def test_cleanup_drops_list_markers():
    out = _cleanup_unsupported_markdown("- one\n- two")
    assert "- " not in out


def test_cleanup_downgrades_h1():
    out = _cleanup_unsupported_markdown("# 标题")
    assert out.startswith("## 标题")


def test_cleanup_strips_code_fence():
    out = _cleanup_unsupported_markdown("```\ncode\n```")
    assert "```" not in out
    assert "code" in out


def test_cleanup_keeps_h2_and_bold():
    text = "## 小标题\n\n段落 **加粗** 内容"
    assert _cleanup_unsupported_markdown(text) == text


def test_cleanup_strips_links():
    assert "http" not in _cleanup_unsupported_markdown("看这里 [链接](https://e.com)")


def test_single_source_heavy_short_content_false():
    assert _single_source_heavy("短") is False
