"""generate-section 的 mode + 上下文切片纯函数测试。"""

from __future__ import annotations

import pytest

from app.services.writing_service import _context_for_section


OUTLINE = [
    {"section_key": "lead", "title": "导语", "goal": ""},
    {"section_key": "bg", "title": "背景", "goal": ""},
    {"section_key": "ana", "title": "分析", "goal": ""},
]

CONTENT = (
    "## 导语\n\n导语正文第一段。\n\n导语正文第二段。\n\n"
    "## 背景\n\n背景内容。\n\n"
    "## 分析\n\n旧的分析正文 A。\n\n旧的分析正文 B。"
)


def test_generate_mode_only_gives_previous_sections():
    out = _context_for_section(CONTENT, "ana", OUTLINE, "generate")
    assert "## 背景" in out
    assert "## 导语" in out
    # generate / regenerate 不应包含当前 section 的旧内容
    assert "旧的分析正文" not in out


def test_regenerate_mode_excludes_current_section_body():
    out = _context_for_section(CONTENT, "ana", OUTLINE, "regenerate")
    assert "## 背景" in out
    assert "旧的分析正文" not in out


def test_continue_mode_includes_current_section_body():
    out = _context_for_section(CONTENT, "ana", OUTLINE, "continue")
    assert "## 分析" in out
    assert "旧的分析正文 B" in out  # 续写需要看到最后一段


def test_continue_first_section_only_has_current():
    only_lead = "## 导语\n\n导语首段。"
    out = _context_for_section(only_lead, "lead", OUTLINE, "continue")
    assert "## 导语" in out
    assert "导语首段" in out


def test_generate_first_section_no_prior_content_returns_empty():
    out = _context_for_section("", "lead", OUTLINE, "generate")
    assert out == ""
    # 草稿只有其它 section 的情况，lead 的 generate 应该给空（没有前文可衔接）
    only_bg = "## 背景\n\nbg body"
    out2 = _context_for_section(only_bg, "lead", OUTLINE, "generate")
    # lead 在 outline 第 0 位，没有更前的 section；函数返回空
    assert out2 == ""


def test_regenerate_current_section_at_end_still_drops_old_body():
    content = "## 导语\n\nhi.\n\n## 分析\n\n旧 body"
    out = _context_for_section(content, "ana", OUTLINE, "regenerate")
    assert "旧 body" not in out
    assert "## 导语" in out
