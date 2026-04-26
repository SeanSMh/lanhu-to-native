"""/api/v1/writing/* — 7 个接口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.writing import (
    FormatRequest,
    FormatResponse,
    GenerateAnglesRequest,
    GenerateAnglesResponse,
    GenerateArticleRequest,
    GenerateArticleResponse,
    GenerateOutlineRequest,
    GenerateOutlineResponse,
    GenerateSectionRequest,
    GenerateSectionResponse,
    PrepublishCheckRequest,
    PrepublishCheckResponse,
    RewriteRequest,
    RewriteResponse,
)
from app.services import writing_service as svc

router = APIRouter(prefix="/writing", tags=["writing"])


@router.post("/generate-angles", response_model=GenerateAnglesResponse)
async def generate_angles_endpoint(
    payload: GenerateAnglesRequest, user: CurrentUser, session: DbSession
) -> GenerateAnglesResponse:
    return await svc.generate_angles(
        session,
        user_id=user.id,
        event_id=payload.event_id,
        style_profile_id=payload.style_profile_id,
    )


@router.post("/generate-outline", response_model=GenerateOutlineResponse)
async def generate_outline_endpoint(
    payload: GenerateOutlineRequest, user: CurrentUser, session: DbSession
) -> GenerateOutlineResponse:
    return await svc.generate_outline(
        session,
        user_id=user.id,
        event_id=payload.event_id,
        angle_type=payload.angle_type,
        style_profile_id=payload.style_profile_id,
    )


@router.post("/generate-article", response_model=GenerateArticleResponse)
async def generate_article_endpoint(
    payload: GenerateArticleRequest, user: CurrentUser, session: DbSession
) -> GenerateArticleResponse:
    return await svc.generate_article(
        session,
        user_id=user.id,
        event_id=payload.event_id,
        angle_type=payload.angle_type,
        mode=payload.mode,
        style_profile_id=payload.style_profile_id,
    )


@router.post("/generate-section", response_model=GenerateSectionResponse)
async def generate_section_endpoint(
    payload: GenerateSectionRequest, user: CurrentUser, session: DbSession
) -> GenerateSectionResponse:
    return await svc.generate_section(
        session,
        user_id=user.id,
        draft_id=payload.draft_id,
        section_key=payload.section_key,
        mode=payload.mode,
    )


@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_endpoint(
    payload: RewriteRequest, user: CurrentUser, session: DbSession
) -> RewriteResponse:
    return await svc.rewrite_text(
        session,
        user_id=user.id,
        draft_id=payload.draft_id,
        target_text=payload.target_text,
        mode=payload.mode,
        style_profile_id=payload.style_profile_id,
    )


@router.post("/format", response_model=FormatResponse)
async def format_endpoint(
    payload: FormatRequest, user: CurrentUser, session: DbSession
) -> FormatResponse:
    return await svc.format_draft(session, draft_id=payload.draft_id)


@router.post("/prepublish-check", response_model=PrepublishCheckResponse)
async def prepublish_check_endpoint(
    payload: PrepublishCheckRequest, user: CurrentUser, session: DbSession
) -> PrepublishCheckResponse:
    return await svc.prepublish_check(session, user_id=user.id, draft_id=payload.draft_id)
