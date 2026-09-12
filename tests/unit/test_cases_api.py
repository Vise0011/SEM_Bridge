"""Tests for case intake routes."""

import httpx
import pytest

from sme_bridge.main import app


def valid_profile_payload() -> dict[str, object]:
    return {
        "business_type": "CORPORATION",
        "established_date": "2023-03-15",
        "hq_region": "대전",
        "industry_code": "J62",
        "employee_count": 8,
        "annual_sales_band": "UNDER_1B_KRW",
        "certifications": [],
        "funding_purpose": "WORKING_CAPITAL",
        "query_date": "2026-09-12",
    }


@pytest.mark.asyncio
async def test_create_case_accepts_valid_profile() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/cases", json=valid_profile_payload())

    body = response.json()
    assert response.status_code == 201
    assert body["case_id"].startswith("case_")
    assert len(body["case_id"]) == 37
    assert body["status"] == "RULE_CHECKED"
    assert body["profile"]["hq_region"] == "대전"
    assert body["programs"][0]["program_id"] == "PBLN_DEMO"
    assert body["programs"][0]["status"] == "PASS"
    assert len(body["programs"][0]["rule_results"]) == 7
    assert body["programs"][0]["missing_fields"] == []
    assert body["programs"][0]["review_required"] is False


@pytest.mark.asyncio
async def test_create_case_rejects_invalid_profile() -> None:
    payload = valid_profile_payload()
    payload["employee_count"] = -1

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/cases", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_case_returns_unknown_for_missing_region() -> None:
    payload = valid_profile_payload()
    del payload["hq_region"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/cases", json=payload)

    assert response.status_code == 201
    program = response.json()["programs"][0]
    assert program["status"] == "UNKNOWN"
    assert program["rule_results"][0]["reason_code"] == "MISSING_VALUE"
    assert program["missing_fields"] == ["hq_region"]
    assert program["follow_up_questions"] == ["기업의 본사 소재 지역을 알려주세요."]
    assert program["review_required"] is True


@pytest.mark.asyncio
async def test_create_case_prioritizes_fail_over_unknown() -> None:
    payload = valid_profile_payload()
    del payload["hq_region"]
    payload["employee_count"] = 11

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/cases", json=payload)

    assert response.status_code == 201
    assert response.json()["programs"][0]["status"] == "FAIL"


@pytest.mark.asyncio
async def test_get_case_returns_saved_snapshot() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post("/v1/cases", json=valid_profile_payload())
        created = created_response.json()
        response = await client.get(f"/v1/cases/{created['case_id']}")

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.asyncio
async def test_get_case_returns_404_when_missing() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/cases/case_missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found"}
