from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_API_TOKEN, skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


async def test_login_ok(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"api_token": TEST_API_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["nickname"] == "我"
    assert body["user"]["id"]
    assert body["user"]["created_at"].endswith("Z") or "+" in body["user"]["created_at"]


async def test_login_wrong_token(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"api_token": "wrong"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


async def test_me_ok(client: AsyncClient, auth_header):
    r = await client.get("/api/v1/auth/me", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["user"]["nickname"] == "我"


async def test_me_no_token(client: AsyncClient):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


async def test_me_invalid_token(client: AsyncClient):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"
