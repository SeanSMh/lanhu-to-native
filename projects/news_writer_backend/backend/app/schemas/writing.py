from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.draft import OutlineSection


AngleType = Literal[
    "fact_summary", "trend", "impact_on_people", "industry_view", "developer_view"
]
RewriteMode = Literal["shorter", "longer", "stronger_opinion", "more_natural", "more_like_me"]
SectionMode = Literal["generate", "continue", "regenerate"]
ArticleMode = Literal["short", "long"]

ANGLE_TYPES = ("fact_summary", "trend", "impact_on_people", "industry_view", "developer_view")
REWRITE_MODES = ("shorter", "longer", "stronger_opinion", "more_natural", "more_like_me")
SECTION_MODES = ("generate", "continue", "regenerate")
ARTICLE_MODES = ("short", "long")


class AngleItem(BaseModel):
    angle_type: str
    label: str
    pitch: str
    expected_word_count: int


class GenerateAnglesRequest(BaseModel):
    event_id: str
    style_profile_id: str | None = None


class GenerateAnglesResponse(BaseModel):
    angles: list[AngleItem]


class GenerateOutlineRequest(BaseModel):
    event_id: str
    angle_type: AngleType
    style_profile_id: str | None = None


class GenerateOutlineResponse(BaseModel):
    title_candidates: list[str]
    outline: list[OutlineSection]


class GenerateSectionRequest(BaseModel):
    draft_id: str
    section_key: str
    mode: SectionMode = "generate"


class GenerateSectionResponse(BaseModel):
    section_key: str
    content_markdown: str


class RewriteRequest(BaseModel):
    draft_id: str
    target_text: str = Field(min_length=1, max_length=1000)
    mode: RewriteMode
    style_profile_id: str | None = None


class RewriteResponse(BaseModel):
    rewritten_text: str


class FormatRequest(BaseModel):
    draft_id: str


class FormatResponse(BaseModel):
    formatted_content_markdown: str


class PrepublishCheckRequest(BaseModel):
    draft_id: str


class PrepublishIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    hint: str


class PrepublishCheckResponse(BaseModel):
    issues: list[PrepublishIssue]


class StyleContext(BaseModel):
    """抽出来给 LLM prompt 用的风格上下文。"""

    model_config = ConfigDict(extra="ignore")

    tone: str | None = None
    structure: str | None = None
    paragraph: str | None = None
    headline: str | None = None
    forbidden_words: list[str] = Field(default_factory=list)
    preset: str | None = None  # style_profile.prompt_preset，最强约束


class GenerateArticleRequest(BaseModel):
    """一次 LLM 调用直出整篇文章（标题 + 正文）。"""

    event_id: str
    angle_type: AngleType
    mode: ArticleMode = "short"
    style_profile_id: str | None = None


class GenerateArticleResponse(BaseModel):
    title: str
    content_markdown: str
