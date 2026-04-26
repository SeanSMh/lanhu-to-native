"""/api/v1/images/* 与 /api/v1/drafts/{id}/image-slots — 5 个接口。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.image import (
    AttachRequest,
    AttachResponse,
    ImageCandidateListResponse,
    ImageSlotsResponse,
    RecommendRequest,
    SearchRequest,
    UploadResponse,
)
from app.services import image_service as svc

router = APIRouter(prefix="/images", tags=["images"])


@router.post("/recommend", response_model=ImageCandidateListResponse)
async def recommend_endpoint(
    payload: RecommendRequest, user: CurrentUser, session: DbSession
) -> ImageCandidateListResponse:
    candidates = await svc.recommend_images(
        session,
        draft_id=payload.draft_id,
        paragraph_text=payload.paragraph_text,
        event_id=payload.event_id,
        preferred_type=payload.preferred_type,
    )
    return ImageCandidateListResponse(candidates=candidates)


@router.post("/search", response_model=ImageCandidateListResponse)
async def search_endpoint(
    payload: SearchRequest, user: CurrentUser, session: DbSession
) -> ImageCandidateListResponse:
    candidates = await svc.search_images(session, keyword=payload.keyword, limit=payload.limit)
    return ImageCandidateListResponse(candidates=candidates)


@router.post("/attach", response_model=AttachResponse, status_code=status.HTTP_201_CREATED)
async def attach_endpoint(
    payload: AttachRequest, user: CurrentUser, session: DbSession
) -> AttachResponse:
    asset = await svc.attach_image(
        session,
        draft_id=payload.draft_id,
        source_image_asset_id=payload.source_image_asset_id,
        caption=payload.caption,
        display_mode=payload.display_mode,
    )
    return AttachResponse(image_asset=asset)


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_endpoint(
    user: CurrentUser,
    session: DbSession,
    file: UploadFile = File(...),
    owner_type: str = Form(default="library"),
    owner_id: str | None = Form(default=None),
) -> UploadResponse:
    data = await file.read()
    asset = await svc.upload_image(
        session,
        data=data,
        filename=file.filename or "upload.jpg",
        owner_type=owner_type,
        owner_id=owner_id,
    )
    return UploadResponse(image_asset=asset)


# /drafts/{id}/image-slots 挂在这里（契约定义路径在 drafts 下），用独立 router
slots_router = APIRouter(prefix="/drafts", tags=["images"])


@slots_router.get("/{draft_id}/image-slots", response_model=ImageSlotsResponse)
async def image_slots_endpoint(
    draft_id: str, user: CurrentUser, session: DbSession
) -> ImageSlotsResponse:
    slots = await svc.image_slots_for_draft(session, draft_id)
    return ImageSlotsResponse(slots=slots)
