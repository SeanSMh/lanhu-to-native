"""Writing API service：6 个接口对应的业务。

每个生成接口只负责：
  1. 校验输入（event / draft 存在、angle_type 枚举等）
  2. 组装 variables
  3. 调 run_llm_job
  4. 按 api-contract 形状返回

prepublish-check 不走 LLM，走规则。
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DraftNotFound,
    EventNotFound,
    StyleProfileNotFound,
    ValidationFailed,
)
from app.models.draft import Draft
from app.models.event import Event
from app.models.style_profile import StyleProfile
from app.schemas.writing import (
    ANGLE_TYPES,
    ARTICLE_MODES,
    AngleItem,
    FormatResponse,
    GenerateAnglesResponse,
    GenerateArticleResponse,
    GenerateOutlineResponse,
    GenerateSectionResponse,
    PrepublishCheckResponse,
    PrepublishIssue,
    RewriteResponse,
    StyleContext,
)
from app.schemas.draft import OutlineSection
from app.services.llm_service import run_llm_job


# --------- 上下文加载 ----------


async def _load_event(session: AsyncSession, event_id: str) -> Event:
    evt = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
    if evt is None:
        raise EventNotFound("事件不存在", {"event_id": event_id})
    return evt


async def _load_draft(session: AsyncSession, draft_id: str) -> Draft:
    d = (await session.execute(select(Draft).where(Draft.id == draft_id))).scalar_one_or_none()
    if d is None:
        raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
    return d


async def _load_style(
    session: AsyncSession, user_id: str, style_profile_id: str | None
) -> StyleContext:
    profile: StyleProfile | None = None
    if style_profile_id:
        profile = (
            await session.execute(
                select(StyleProfile).where(StyleProfile.id == style_profile_id)
            )
        ).scalar_one_or_none()
        if profile is None:
            raise StyleProfileNotFound(
                "风格配置不存在", {"style_profile_id": style_profile_id}
            )
    else:
        # 即使历史数据里意外出现多条 is_default=true（约束未落地前的脏数据），
        # 这里也不会 500；取最近更新的一条兜底。新 migration 之后写入路径已由
        # 部分唯一索引保证只有一条。
        profile = (
            await session.execute(
                select(StyleProfile)
                .where(
                    StyleProfile.user_id == user_id, StyleProfile.is_default.is_(True)
                )
                .order_by(StyleProfile.updated_at.desc(), StyleProfile.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if profile is None:
        return StyleContext()
    return StyleContext(
        tone=profile.tone,
        structure=profile.preferred_structure,
        paragraph=profile.paragraph_style,
        headline=profile.headline_style,
        forbidden_words=list(profile.forbidden_words_json or []),
        preset=profile.prompt_preset,
    )


# --------- 6 个接口 ----------


async def generate_angles(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    style_profile_id: str | None,
) -> GenerateAnglesResponse:
    evt = await _load_event(session, event_id)
    style = await _load_style(session, user_id, style_profile_id)
    result = await run_llm_job(
        session,
        job_type="generate_angles",
        prompt_template_id="angle_generation",
        variables={
            "event_summary": evt.summary or evt.title,
            "timeline_json": evt.timeline_json or [],
            "style_tone": style.tone or "",
            "style_structure": style.structure or "",
            "style_forbidden_words": style.forbidden_words,
            "style_preset": style.preset or "",
        },
    )
    raw_angles = result.get("angles") or []
    angles = [
        AngleItem(
            angle_type=a.get("angle_type", "fact_summary"),
            label=a.get("label", ""),
            pitch=a.get("pitch", ""),
            expected_word_count=int(a.get("expected_word_count") or 800),
        )
        for a in raw_angles
        if isinstance(a, dict)
    ]
    return GenerateAnglesResponse(angles=angles)


async def generate_outline(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    angle_type: str,
    style_profile_id: str | None,
) -> GenerateOutlineResponse:
    if angle_type not in ANGLE_TYPES:
        raise ValidationFailed("angle_type 不合法", {"angle_type": angle_type})
    evt = await _load_event(session, event_id)
    style = await _load_style(session, user_id, style_profile_id)
    # 用 event 的 suggested_angles 里找到对应 pitch；找不到就以 label 兜底
    angle_pitch = ""
    for a in evt.suggested_angles_json or []:
        if isinstance(a, dict) and a.get("angle_type") == angle_type:
            angle_pitch = a.get("one_liner") or a.get("label") or ""
            break

    result = await run_llm_job(
        session,
        job_type="generate_outline",
        prompt_template_id="outline_generation",
        variables={
            "event_summary": evt.summary or evt.title,
            "angle_type": angle_type,
            "angle_pitch": angle_pitch,
            "style_tone": style.tone or "",
            "style_structure": style.structure or "",
            "style_paragraph": style.paragraph or "",
            "style_headline": style.headline or "",
            "style_forbidden_words": style.forbidden_words,
            "style_preset": style.preset or "",
        },
    )
    titles = [str(t) for t in (result.get("title_candidates") or [])]
    outline_raw = result.get("outline") or []
    outline = [
        OutlineSection(
            section_key=s["section_key"],
            title=s.get("title", ""),
            goal=s.get("goal", ""),
        )
        for s in outline_raw
        if isinstance(s, dict) and "section_key" in s
    ]
    return GenerateOutlineResponse(title_candidates=titles, outline=outline)


async def generate_section(
    session: AsyncSession,
    *,
    user_id: str,
    draft_id: str,
    section_key: str,
    mode: str,
) -> GenerateSectionResponse:
    if mode not in ("generate", "continue", "regenerate"):
        raise ValidationFailed("mode 不合法", {"mode": mode})
    draft = await _load_draft(session, draft_id)
    outline = list(draft.outline_json or [])
    target = next(
        (s for s in outline if isinstance(s, dict) and s.get("section_key") == section_key),
        None,
    )
    if target is None:
        raise ValidationFailed(
            "section_key 不在草稿大纲中", {"section_key": section_key}
        )
    evt = await _load_event(session, draft.event_id)
    style = await _load_style(session, user_id, draft.style_profile_id)
    result = await run_llm_job(
        session,
        job_type="generate_section",
        prompt_template_id="section_generation",
        variables={
            "event_summary": evt.summary or evt.title,
            "outline_json": outline,
            "section_key": section_key,
            "section_title": target.get("title", ""),
            "section_goal": target.get("goal", ""),
            "mode": mode,
            "previous_content": _context_for_section(
                draft.content_markdown or "", section_key, outline, mode
            ),
            "style_tone": style.tone or "",
            "style_paragraph": style.paragraph or "",
            "style_forbidden_words": style.forbidden_words,
            "style_preset": style.preset or "",
        },
    )
    return GenerateSectionResponse(
        section_key=section_key,
        content_markdown=str(result.get("content_markdown") or ""),
    )


async def generate_article(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    angle_type: str,
    mode: str,
    style_profile_id: str | None,
) -> GenerateArticleResponse:
    """一次 LLM 调用直出整篇文章（标题 + 正文）。

    用 mode 区分长短文写作目标；style_profile.preset 在 prompt 末尾以"用户额外约束"
    形式注入，优先级最高。"""
    if angle_type not in ANGLE_TYPES:
        raise ValidationFailed("angle_type 不合法", {"angle_type": angle_type})
    if mode not in ARTICLE_MODES:
        raise ValidationFailed("mode 不合法", {"mode": mode})

    evt = await _load_event(session, event_id)
    style = await _load_style(session, user_id, style_profile_id)

    angle_pitch = ""
    for a in evt.suggested_angles_json or []:
        if isinstance(a, dict) and a.get("angle_type") == angle_type:
            angle_pitch = a.get("one_liner") or a.get("label") or ""
            break

    target = (
        "100-300 字（不超过 350）；分 1-3 段；每段 2-3 句"
        if mode == "short"
        else "800-1200 字；分 4-6 段；每段 3-5 句"
    )

    result = await run_llm_job(
        session,
        job_type="generate_article",
        prompt_template_id="generate_article",
        variables={
            "event_summary": evt.summary or evt.title,
            "timeline_json": evt.timeline_json or [],
            "angle_type": angle_type,
            "angle_pitch": angle_pitch,
            "mode": mode,
            "length_target": target,
            "style_tone": style.tone or "",
            "style_structure": style.structure or "",
            "style_paragraph": style.paragraph or "",
            "style_headline": style.headline or "",
            "style_forbidden_words": style.forbidden_words,
            "style_preset": style.preset or "",
        },
    )
    return GenerateArticleResponse(
        title=str(result.get("title") or ""),
        content_markdown=str(result.get("content_markdown") or ""),
    )


MAX_CONTEXT_CHARS = 1200


def _section_titles_and_keys(outline: list) -> tuple[list[str], list[str]]:
    keys = [s.get("section_key", "") for s in outline if isinstance(s, dict)]
    titles = [s.get("title", "") for s in outline if isinstance(s, dict)]
    return keys, titles


def _split_section(content: str, target_title: str, next_title: str | None) -> tuple[str, str]:
    """返回 (before_target_section, current_section_body)；找不到则 before=content, current=''。

    current_section_body 包含自身的 `## 标题` 行；切到下个 section 之前。
    """
    if not target_title or f"## {target_title}" not in content:
        return content, ""
    before, after = content.split(f"## {target_title}", 1)
    current = f"## {target_title}{after}"
    if next_title and f"## {next_title}" in current:
        current = current.split(f"## {next_title}")[0]
    return before, current


def _context_for_section(content: str, section_key: str, outline: list, mode: str) -> str:
    """按 mode 决定喂给 LLM 的上下文。

    - generate / regenerate: 只给本 section 之前已写好的内容
    - continue: 在此基础上再拼接本 section 已有的草稿末尾，模型据此续写

    语义上第一节（idx==0）没有"前面 section"。即便用户把别的 section 写在了前面，
    此函数也不把那些错位内容当成 lead 的上文。
    """
    if not content:
        return ""
    keys, titles = _section_titles_and_keys(outline)
    try:
        idx = keys.index(section_key)
    except ValueError:
        return content[-MAX_CONTEXT_CHARS:]
    target_title = titles[idx] if idx < len(titles) else ""
    next_title = titles[idx + 1] if idx + 1 < len(titles) else None
    before, current_body = _split_section(content, target_title, next_title)

    if idx == 0:
        before_slice = ""  # 第一节没有"前面"
    else:
        before_slice = before[-MAX_CONTEXT_CHARS:]

    if mode == "continue" and current_body.strip():
        body_slice = current_body[-MAX_CONTEXT_CHARS:]
        if before_slice:
            combined = before_slice + "\n\n" + body_slice
        else:
            combined = body_slice
        return combined[-2 * MAX_CONTEXT_CHARS:].strip()
    # generate / regenerate：丢弃本 section 旧内容
    return before_slice


async def rewrite_text(
    session: AsyncSession,
    *,
    user_id: str,
    draft_id: str,
    target_text: str,
    mode: str,
    style_profile_id: str | None,
) -> RewriteResponse:
    await _load_draft(session, draft_id)  # 校验存在
    style = await _load_style(session, user_id, style_profile_id)
    result = await run_llm_job(
        session,
        job_type="rewrite",
        prompt_template_id="rewrite",
        variables={
            "target_text": target_text,
            "mode": mode,
            "style_tone": style.tone or "",
            "style_paragraph": style.paragraph or "",
            "style_forbidden_words": style.forbidden_words,
            "style_preset": style.preset or "",
        },
    )
    return RewriteResponse(rewritten_text=str(result.get("rewritten_text") or ""))


async def format_draft(
    session: AsyncSession, *, draft_id: str
) -> FormatResponse:
    draft = await _load_draft(session, draft_id)
    result = await run_llm_job(
        session,
        job_type="format",
        prompt_template_id="format_for_toutiao",
        variables={"content_markdown": draft.content_markdown or ""},
    )
    formatted = str(result.get("formatted_content_markdown") or "")
    return FormatResponse(formatted_content_markdown=_cleanup_unsupported_markdown(formatted))


# --------- prepublish-check：规则 ---------


SUBJECTIVE_MARKERS = ["我认为", "我觉得", "关键在于", "值得关注", "不得不说", "依我看"]
ATTRIBUTION_MARKERS = ["据悉", "据报道", "据", "报道称", "消息人士"]
SOURCE_KEYWORD = "来源"


async def prepublish_check(
    session: AsyncSession, *, user_id: str, draft_id: str
) -> PrepublishCheckResponse:
    draft = await _load_draft(session, draft_id)
    style = await _load_style(session, user_id, draft.style_profile_id)
    content = draft.content_markdown or ""
    title = draft.title or ""

    issues: list[PrepublishIssue] = []

    # paragraph_too_long
    for i, para in enumerate(p.strip() for p in content.split("\n\n") if p.strip()):
        if len(para) > 400:
            issues.append(
                PrepublishIssue(
                    severity="info",
                    code="paragraph_too_long",
                    message=f"第 {i + 1} 段长度 {len(para)} 字，手机阅读吃力",
                    hint="考虑拆成两段",
                )
            )
            break  # 只报一次

    # title_too_long
    if len(title) > 25:
        issues.append(
            PrepublishIssue(
                severity="warning",
                code="title_too_long",
                message=f"标题 {len(title)} 字，超过 25 字阈值",
                hint="精简标题，突出核心冲突",
            )
        )

    # too_many_clickbait_words
    forbidden = style.forbidden_words or []
    hits = [w for w in forbidden if w and w in (title + content)]
    if len(hits) >= 2:
        issues.append(
            PrepublishIssue(
                severity="warning",
                code="too_many_clickbait_words",
                message=f"命中禁用词 {len(hits)} 个：{', '.join(hits[:5])}",
                hint="换成客观表达",
            )
        )

    # missing_opinion
    if not any(m in content for m in SUBJECTIVE_MARKERS):
        issues.append(
            PrepublishIssue(
                severity="info",
                code="missing_opinion",
                message="通篇未见主观判断，文章可能流于陈述",
                hint="在结尾或核心段加一句你的观点",
            )
        )

    # missing_attribution
    if any(m in content for m in ATTRIBUTION_MARKERS) and SOURCE_KEYWORD not in content:
        issues.append(
            PrepublishIssue(
                severity="info",
                code="missing_attribution",
                message="出现'据悉/报道'等引用但未说明来源",
                hint="在引用段后补充原始来源",
            )
        )

    # single_source_heavy
    if _single_source_heavy(content):
        issues.append(
            PrepublishIssue(
                severity="warning",
                code="single_source_heavy",
                message="全文内容集中依赖单一来源",
                hint="补充第二来源印证",
            )
        )

    return PrepublishCheckResponse(issues=issues)


def _single_source_heavy(content: str) -> bool:
    """估算：正文中单一实体（长度 ≥ 2 的字符序列）出现频次是否 >70% 的名词类占比。

    MVP 粗略版：只看"同一源名称是否高频出现"。找出形如 'XX' 多次出现的词。
    """
    if len(content) < 200:
        return False
    tokens = re.findall(r"[一-鿿A-Za-z]{2,8}", content)
    if not tokens:
        return False
    from collections import Counter

    cnt = Counter(tokens)
    total = sum(cnt.values())
    top_word, top_n = cnt.most_common(1)[0]
    return top_n >= 5 and top_n / total > 0.12 and len(top_word) >= 2


def _cleanup_unsupported_markdown(text: str) -> str:
    """按 shared §8.5 清理 LLM 意外输出的不支持语法。"""
    if not text:
        return text
    lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        # 代码块去掉围栏
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            lines.append(line)  # 代码块内部文本保留为普通文本
            continue
        # 一级标题降为二级；三级以下降为普通段
        if stripped.startswith("# ") and not stripped.startswith("## "):
            lines.append("## " + stripped[2:])
            continue
        if stripped.startswith("### "):
            lines.append(stripped[4:])
            continue
        if stripped.startswith("#### "):
            lines.append(stripped[5:])
            continue
        # 列表
        if re.match(r"^\s*[-*]\s+", line):
            lines.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            lines.append(re.sub(r"^\s*\d+\.\s+", "", line))
            continue
        # 引用块
        if stripped.startswith(">"):
            lines.append(stripped.lstrip(">").strip())
            continue
        # 水平线
        if stripped in ("---", "***", "___"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    # 删除链接 [text](url) → text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return cleaned
