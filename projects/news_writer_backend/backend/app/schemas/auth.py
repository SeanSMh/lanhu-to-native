from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    nickname: str
    created_at: datetime


class LoginRequest(BaseModel):
    api_token: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    user: UserOut
