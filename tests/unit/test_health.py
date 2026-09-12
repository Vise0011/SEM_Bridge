"""Tests for the API health endpoint."""

import httpx
import pytest

from sme_bridge.main import app


@pytest.mark.asyncio
async def test_health_returns_service_status() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sme-bridge",
        "version": "0.1.0",
    }
