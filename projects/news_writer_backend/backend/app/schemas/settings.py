from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StyleProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tone: str | None = None
    forbidden_words: list[str] = Field(default_factory=list)
    preferred_structure: str | None = None
    paragraph_style: str | None = None
    headline_style: str | None = None
    prompt_preset: str | None = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class StyleProfileListResponse(BaseModel):
    items: list[StyleProfileOut]


class StyleProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tone: str | None = None
    forbidden_words: list[str] = Field(default_factory=list)
    preferred_structure: str | None = None
    paragraph_style: str | None = None
    headline_style: str | None = None
    prompt_preset: str | None = None
    is_default: bool = False


class StyleProfileUpdate(BaseModel):
    name: str | None = None
    tone: str | None = None
    forbidden_words: list[str] | None = None
    preferred_structure: str | None = None
    paragraph_style: str | None = None
    headline_style: str | None = None
    prompt_preset: str | None = None
    is_default: bool | None = None


class ModelSettingsResponse(BaseModel):
    llm_base_url: str
    llm_model: str
    llm_api_key_configured: bool
    source: dict[str, str]


class ModelSettingsPatch(BaseModel):
    llm_base_url: str | None = None
    llm_model: str | None = None
