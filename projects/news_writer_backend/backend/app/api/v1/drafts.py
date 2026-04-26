"""/api/v1/drafts/* — 7 个接口。"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.draft import (
    DraftCompleteResponse,
    DraftCreate,
    DraftDetailResponse,
    DraftDuplicate,
    DraftListResponse,
    DraftSnapshotCreate,
    DraftSnapshotResponse,
    DraftUpdate,
)
from app.services.draft_service import DraftService

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.post("", response_model=DraftDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: DraftCreate, user: CurrentUser, session: DbSession
) -> DraftDetailResponse:
    detail = await DraftService(session).create(user.id, payload)
    return DraftDetailResponse(draft=detail)


@router.get("", response_model=DraftListResponse)
async def list_drafts(
    user: CurrentUser,
    session: DbSession,
    status_: str | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> DraftListResponse:
    items, next_cursor = await DraftService(session).list(user.id, status_, cursor, limit)
    return DraftListResponse(items=items, next_cursor=next_cursor)


@router.get("/{draft_id}", response_model=DraftDetailResponse)
async def get_draft(
    draft_id: str, user: CurrentUser, session: DbSession
) -> DraftDetailResponse:
    detail = await DraftService(session).get_detail(draft_id)
    return DraftDetailResponse(draft=detail)


@router.patch("/{draft_id}", response_model=DraftDetailResponse)
async def update_draft(
    draft_id: str, payload: DraftUpdate, user: CurrentUser, session: DbSession
) -> DraftDetailResponse:
    detail = await DraftService(session).update(draft_id, user.id, payload)
    return DraftDetailResponse(draft=detail)


@router.post(
    "/{draft_id}/snapshot",
    response_model=DraftSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def snapshot_draft(
    draft_id: str,
    payload: DraftSnapshotCreate,
    user: CurrentUser,
    session: DbSession,
) -> DraftSnapshotResponse:
    version = await DraftService(session).snapshot(draft_id, payload.reason)
    return DraftSnapshotResponse(version=version)


@router.post(
    "/{draft_id}/duplicate",
    response_model=DraftDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_draft(
    draft_id: str, payload: DraftDuplicate, user: CurrentUser, session: DbSession
) -> DraftDetailResponse:
    detail = await DraftService(session).duplicate(
        draft_id, user.id, payload.new_id, payload.new_title
    )
    return DraftDetailResponse(draft=detail)


@router.post("/{draft_id}/complete", response_model=DraftCompleteResponse)
async def complete_draft(
    draft_id: str, user: CurrentUser, session: DbSession
) -> DraftCompleteResponse:
    detail, article_id = await DraftService(session).complete(draft_id, user.id)
    return DraftCompleteResponse(draft=detail, article_id=article_id)
