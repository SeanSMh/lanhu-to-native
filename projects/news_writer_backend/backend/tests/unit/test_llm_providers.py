"""测试 LLM provider 抽象与 fake 实现。"""

from __future__ import annotations

import pytest

from app.providers.llm.fake import FIXTURES, FakeLLMProvider
from app.providers.llm.openai_compat import _extract_json
from app.services.llm_service import _load_template, _render


def test_load_all_7_prompt_templates():
    for name in (
        "event_summary",
        "angle_generation",
        "outline_generation",
        "section_generation",
        "rewrite",
        "format_for_toutiao",
        "image_slot_recommendation",
    ):
        system, user = _load_template(name)
        assert system
        assert user


def test_render_safe_substitute_keeps_missing_placeholder():
    out = _render("hello ${name}, miss ${x}", {"name": "world"})
    assert out == "hello world, miss ${x}"


def test_render_serialises_non_string_values():
    out = _render("data=${d}", {"d": {"a": 1}})
    assert '"a": 1' in out


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_block():
    assert _extract_json("```json\n{\"x\": 2}\n```") == {"x": 2}


def test_extract_json_fallback_brace():
    assert _extract_json('preamble {"ok": true} trailing') == {"ok": True}


@pytest.mark.asyncio
async def test_fake_llm_event_summary():
    provider = FakeLLMProvider()
    result = await provider.chat_json(
        system="你是一个新闻编辑助理，擅长从多条新闻中提炼出核心事件",
        user="any",
    )
    assert result == FIXTURES["event_summary"]


@pytest.mark.asyncio
async def test_fake_llm_outline():
    provider = FakeLLMProvider()
    result = await provider.chat_json(
        system="你是资深内容编辑，负责为一篇微信/头条风格的中长文章搭骨架",
        user="any",
    )
    assert result == FIXTURES["outline_generation"]
