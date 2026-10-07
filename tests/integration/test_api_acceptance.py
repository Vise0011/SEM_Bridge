"""Acceptance checks using synthetic notices in an isolated, temporary SQLite DB."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.config import Settings
from sme_bridge.main import create_app
from sme_bridge.schemas.document import ParsedPdf, PdfPage
from sme_bridge.schemas.publication import PublicationDraft
from sme_bridge.services.documents import store_parsed_document
from sme_bridge.services.ingestion import build_notice_snapshot
from sme_bridge.services.publication import verify_publication

PROFILE = {"business_type": "CORPORATION", "hq_region": "대전", "query_date": "2026-10-07"}
TEXT = "본사가 대전광역시에 소재한 기업을 지원합니다."


@pytest.fixture
async def local_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    settings = Settings(
        _env_file=None, storage_backend="sqlite", sqlite_path=str(tmp_path / "qa.sqlite3")
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, app


async def test_fresh_local_startup_assets_and_empty_official_result(local_api) -> None:
    client, _ = local_api
    for path in ["/", "/docs", "/openapi.json", "/static/app.js", "/static/style.css"]:
        assert (await client.get(path)).status_code == 200
    icon = await client.get("/static/favicon.svg")
    assert icon.status_code == 200 and "image/svg+xml" in icon.headers["content-type"]
    assert (await client.get("/health")).json()["status"] == "ok"
    assert (await client.get("/ready")).json() == {"status": "ready", "storage": "sqlite"}
    assert (await client.get("/v1/notices")).json()["items"] == []
    response = await client.post("/v1/cases", json=PROFILE)
    assert response.status_code == 201
    case = response.json()
    assert case["source"] == "official" and case["status"] == "REVIEW_PENDING"
    assert case["programs"] == [] and case["notes"]
    assert (await client.get(f"/v1/cases/{case['case_id']}")).json() == case


@pytest.mark.parametrize(
    "path",
    [
        "/v1/notices?limit=0",
        "/v1/notices?limit=101",
        "/v1/notices?offset=-1",
        "/v1/notices?offset=100001",
        "/v1/notices?q=" + "a" * 201,
        "/v1/notices/missing?version=bad-hash",
        "/v1/notices/missing/passages?limit=101",
        "/v1/notices/missing/passages?offset=-1",
        "/v1/notices/missing/passages?version=bad-hash",
    ],
)
async def test_invalid_read_parameters_return_422(local_api, path: str) -> None:
    client, _ = local_api
    assert (await client.get(path)).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/v1/notices/missing",
        "/v1/notices/missing/versions",
        "/v1/notices/missing/passages",
        "/v1/cases/case_missing",
    ],
)
async def test_unknown_resources_return_404(local_api, path: str) -> None:
    client, _ = local_api
    assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize(
    "query,headers",
    [
        ("source=invalid", {}),
        ("source=demo&notice_id=PBLN_QA", {}),
        ("source=demo", {"Idempotency-Key": "unsafe key"}),
        ("source=demo", {"Idempotency-Key": "a" * 129}),
    ],
)
async def test_invalid_case_options_return_422(local_api, query: str, headers: dict) -> None:
    client, _ = local_api
    assert (
        await client.post(f"/v1/cases?{query}", json=PROFILE, headers=headers)
    ).status_code == 422


async def test_notice_pagination_literal_search_and_history(local_api) -> None:
    client, app = local_api
    snapshots = []
    for i in range(3):
        snapshot = build_notice_snapshot(
            BizinfoNotice.model_validate(
                {
                    "pblancId": f"PBLN_QA_{i}",
                    "pblancNm": f"합성 대전 공고 {i}",
                    "pblancUrl": "/synthetic-qa",
                }
            )
        )
        snapshots.append(snapshot)
        await app.state.notice_repository.save(snapshot)
    all_items = (await client.get("/v1/notices?q=대전")).json()["items"]
    first = (await client.get("/v1/notices?limit=2&offset=0")).json()["items"]
    last = (await client.get("/v1/notices?limit=2&offset=2")).json()["items"]
    assert first + last == all_items and len(all_items) == 3
    assert (await client.get("/v1/notices?offset=3")).json()["items"] == []
    # SQL-like text is a literal substring, not a query or wildcard.
    for query in ["%", "' OR 1=1 --", "없는공고"]:
        assert (await client.get("/v1/notices", params={"q": query})).json()["items"] == []
    old = snapshots[0]
    updated = old.model_copy(update={"title": "변경된 합성 공고", "version_hash": "b" * 64})
    await app.state.notice_repository.save(updated)
    assert (await client.get(f"/v1/notices/{old.notice_id}")).json()["snapshot"][
        "title"
    ] == updated.title
    historical = await client.get(
        f"/v1/notices/{old.notice_id}", params={"version": old.version_hash}
    )
    assert historical.json()["snapshot"]["title"] == old.title
    versions = (await client.get(f"/v1/notices/{old.notice_id}/versions")).json()
    assert len(versions) == 2


async def test_reviewed_synthetic_official_contract_all_outcomes_and_stale_history(
    local_api,
) -> None:
    client, app = local_api
    snapshot = build_notice_snapshot(
        BizinfoNotice.model_validate(
            {
                "pblancId": "PBLN_QA",
                "pblancNm": "합성 조건 승인 테스트",
                "pblancUrl": "/synthetic-qa",
            }
        )
    )
    await app.state.notice_repository.save(snapshot)
    await store_parsed_document(
        app.state.document_repository,
        notice_id=snapshot.notice_id,
        notice_version_hash=snapshot.version_hash,
        source_url="https://www.bizinfo.go.kr/qa.pdf",
        parsed=ParsedPdf(
            sha256="a" * 64,
            page_count=2,
            pages=[
                PdfPage(page_number=1, text=TEXT, character_count=len(TEXT), requires_ocr=False),
                PdfPage(
                    page_number=2,
                    text="합성 OCR 검토 페이지",
                    character_count=13,
                    requires_ocr=True,
                ),
            ],
            ocr_required_pages=[2],
        ),
    )
    pages = (await client.get("/v1/notices/PBLN_QA/passages")).json()["items"]
    assert len(pages) == 2 and pages[1]["requires_ocr"]
    assert (await client.get("/v1/notices/PBLN_QA/passages?limit=1&offset=1")).json()[
        "items"
    ] == pages[1:]
    assert (await client.get("/v1/notices/PBLN_QA/passages?q=소재")).json()["items"] == pages[:1]
    evidence_id = f"PBLN_QA:{snapshot.version_hash}:region"
    draft = PublicationDraft.model_validate(
        {
            "notice_id": snapshot.notice_id,
            "version_hash": snapshot.version_hash,
            "approved_by": "synthetic-test-only",
            "scope_complete": True,
            "conditions": [
                {"field": "hq_region", "allowed_regions": ["대전"], "evidence_id": evidence_id}
            ],
            "citations": [
                {
                    "evidence_id": evidence_id,
                    "pdf_sha256": "a" * 64,
                    "page_number": 1,
                    "passage": TEXT,
                }
            ],
        }
    )
    invalid_ocr = draft.model_copy(deep=True)
    invalid_ocr.citations[0].page_number = 2
    invalid_ocr.citations[0].passage = "합성 OCR 검토 페이지"
    with pytest.raises(ValueError, match="OCR or security-flagged"):
        await verify_publication(
            invalid_ocr, app.state.notice_repository, app.state.document_repository
        )
    publication = await verify_publication(
        draft, app.state.notice_repository, app.state.document_repository
    )
    await app.state.official_program_repository.publish(publication)
    saved_cases = []
    for region, expected in [("대전", "PASS"), ("서울", "FAIL"), (None, "UNKNOWN")]:
        response = await client.post(
            "/v1/cases?notice_id=PBLN_QA", json={**PROFILE, "hq_region": region}
        )
        assert response.status_code == 201
        case = response.json()
        result = case["programs"][0]
        assert result["status"] == expected
        assert result["evidence"][0]["pdf_sha256"] == "a" * 64
        assert result["evidence"][0]["notice_version"] == f"sha256:{snapshot.version_hash}"
        assert result["missing_evidence_ids"] == []
        saved_cases.append(case)
    await app.state.notice_repository.save(snapshot.model_copy(update={"version_hash": "c" * 64}))
    after = (await client.post("/v1/cases?notice_id=PBLN_QA", json=PROFILE)).json()
    assert (
        after["programs"][0]["status"] == "UNKNOWN" and after["programs"][0]["rule_results"] == []
    )
    for case in saved_cases:
        assert (await client.get(f"/v1/cases/{case['case_id']}")).json() == case


async def test_ready_detects_missing_repository_and_liveness_stays_ok(local_api) -> None:
    client, app = local_api
    del app.state.notice_repository
    assert (await client.get("/ready")).status_code == 503
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/v1/notices")).status_code == 503
