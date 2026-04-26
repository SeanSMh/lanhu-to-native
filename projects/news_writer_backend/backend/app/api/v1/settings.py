"""/api/v1/style-profiles/* 和 /api/v1/settings/model — 6 个接口。"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.settings import (
    ModelSettingsPatch,
    ModelSettingsResponse,
    StyleProfileCreate,
    StyleProfileListResponse,
    StyleProfileOut,
    StyleProfileUpdate,
)
from app.services import style_profile_service as sp
from app.services import settings_service as ss

style_router = APIRouter(prefix="/style-profiles", tags=["settings"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


@style_router.get("", response_model=StyleProfileListResponse)
async def list_style_profiles(
    user: CurrentUser, session: DbSession
) -> StyleProfileListResponse:
    items = await sp.list_profiles(session, user.id)
    return StyleProfileListResponse(items=items)


@style_router.post(
    "", response_model=StyleProfileOut, status_code=status.HTTP_201_CREATED
)
async def create_style_profile(
    payload: StyleProfileCreate, user: CurrentUser, session: DbSession
) -> StyleProfileOut:
    return await sp.create_profile(session, user.id, payload)


@style_router.patch("/{profile_id}", response_model=StyleProfileOut)
async def update_style_profile(
    profile_id: str,
    payload: StyleProfileUpdate,
    user: CurrentUser,
    session: DbSession,
) -> StyleProfileOut:
    return await sp.update_profile(session, user.id, profile_id, payload)


@style_router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_style_profile(
    profile_id: str, user: CurrentUser, session: DbSession
) -> Response:
    await sp.delete_profile(session, user.id, profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@settings_router.get("/model", response_model=ModelSettingsResponse)
async def get_model_settings(
    user: CurrentUser,
) -> ModelSettingsResponse:
    body = await ss.get_model_settings_full()
    return ModelSettingsResponse(**body)


@settings_router.patch("/model", response_model=ModelSettingsResponse)
async def patch_model_settings(
    payload: ModelSettingsPatch, user: CurrentUser, session: DbSession
) -> ModelSettingsResponse:
    body = await ss.patch_model_settings(
        session, llm_base_url=payload.llm_base_url, llm_model=payload.llm_model
    )
    return ModelSettingsResponse(**body)
