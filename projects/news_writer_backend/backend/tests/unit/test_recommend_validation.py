"""/images/recommend 互斥校验与 preferred_type keyword 构造的纯函数测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.image import RecommendRequest
from app.services.image_service import _build_search_keyword


def test_recommend_schema_rejects_both_modes():
    with pytest.raises(ValidationError):
        RecommendRequest(
            draft_id="01D",
            paragraph_text="x",
            event_id="01E",
        )


def test_recommend_schema_rejects_neither_mode():
    with pytest.raises(ValidationError):
        RecommendRequest()


def test_recommend_schema_accepts_paragraph_mode():
    r = RecommendRequest(draft_id="01D", paragraph_text="正文")
    assert r.draft_id == "01D"


def test_recommend_schema_accepts_event_mode():
    r = RecommendRequest(event_id="01E", preferred_type="hero")
    assert r.event_id == "01E"
    assert r.preferred_type == "hero"


def test_recommend_schema_draft_id_alone_is_incomplete():
    # 段落模式需要 draft_id + paragraph_text 都有
    with pytest.raises(ValidationError):
        RecommendRequest(draft_id="01D")


def test_recommend_schema_paragraph_text_alone_is_incomplete():
    with pytest.raises(ValidationError):
        RecommendRequest(paragraph_text="x")


def test_recommend_schema_rejects_event_id_plus_draft_id():
    """{event_id, draft_id} 混用：客户端大概率组参错，422。"""
    with pytest.raises(ValidationError) as ei:
        RecommendRequest(event_id="01E", draft_id="01D")
    msg = str(ei.value)
    assert "混用" in msg or "不得" in msg


def test_recommend_schema_rejects_event_id_plus_paragraph_text():
    """{event_id, paragraph_text} 混用：同上。"""
    with pytest.raises(ValidationError):
        RecommendRequest(event_id="01E", paragraph_text="x")


def test_recommend_schema_treats_empty_string_as_not_set():
    """客户端如果把空串当 null 传，不应触发混用校验。"""
    r = RecommendRequest(draft_id="01D", paragraph_text="x", event_id="")
    assert r.draft_id == "01D"
    r2 = RecommendRequest(event_id="01E", draft_id="", paragraph_text="   ")
    assert r2.event_id == "01E"


def test_build_keyword_appends_preferred_type_hint():
    kw = _build_search_keyword(
        "AI 办公助手发布，公司主打协作。",
        fallback="",
        preferred_type="product",
    )
    assert "product" in kw
    assert "办公" in kw or "发布" in kw  # 原关键词保留


def test_build_keyword_no_hint_for_none():
    kw = _build_search_keyword(
        "AI 办公助手发布。",
        fallback="",
        preferred_type="none",
    )
    # none 不拼英文补语
    assert "none" not in kw
    assert "cover" not in kw


def test_build_keyword_unknown_type_no_hint():
    kw = _build_search_keyword("AI 办公。", fallback="x", preferred_type=None)
    assert "cover" not in kw
    assert "chart" not in kw
