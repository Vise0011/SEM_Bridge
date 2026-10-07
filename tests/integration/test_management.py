"""Local management authorization, recovery and non-publishing review workflow."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.config import Settings
from sme_bridge.main import create_app
from sme_bridge.repositories.jobs import ActiveCollectionError
from sme_bridge.schemas.document import ParsedPdf, PdfPage
from sme_bridge.schemas.management import CollectionJob, CollectionRequest
from sme_bridge.services.documents import store_parsed_document
from sme_bridge.services.ingestion import build_notice_snapshot


@pytest.fixture
async def management_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    settings = Settings(
        _env_file=None,
        storage_backend="sqlite",
        sqlite_path=str(tmp_path / "test.sqlite3"),
        local_management_enabled=True,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)),
            base_url="http://127.0.0.1:8000",
        ) as client:
            client.headers["X-Bridge-Token"] = (await client.get("/v1/manage/status")).json()[
                "token"
            ]
            yield client, app


async def seed(app, *, ocr=False, kind="PDF"):
    snapshot = build_notice_snapshot(
        BizinfoNotice.model_validate(
            {"pblancId": "TEST", "pblancNm": "합성 검토 공고", "pblancUrl": "/test"}
        )
    )
    await app.state.storage.notices.save(snapshot)
    text = "본사가 대전광역시에 소재한 기업을 지원합니다."
    await store_parsed_document(
        app.state.storage.documents,
        notice_id=snapshot.notice_id,
        notice_version_hash=snapshot.version_hash,
        source_url="https://www.bizinfo.go.kr/test.pdf",
        parsed=ParsedPdf(
            sha256="a" * 64,
            page_count=1,
            ocr_required_pages=[1] if ocr else [],
            pages=[
                PdfPage(
                    page_number=1,
                    text=text,
                    character_count=len(text),
                    requires_ocr=ocr,
                    document_kind=kind,
                    location_kind="SECTION" if kind == "HWPX" else "PAGE",
                )
            ],
        ),
    )
    return snapshot


async def test_management_requires_token_origin_loopback_and_enabled(management_api):
    client, app = management_api
    assert (await client.get("/v1/manage/jobs")).status_code == 200
    assert (
        await client.get("/v1/manage/jobs", headers={"X-Bridge-Token": "wrong"})
    ).status_code == 403
    for headers in [{"Origin": "https://evil.example"}, {"Host": "evil.example"}]:
        assert (await client.get("/v1/manage/status", headers=headers)).status_code == 403
        assert (await client.post("/v1/manage/jobs", json={}, headers=headers)).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 1234)),
        base_url="http://127.0.0.1:8000",
    ) as remote:
        assert (await remote.get("/v1/manage/status")).status_code == 403
    app.state.settings.local_management_enabled = False
    assert (await client.get("/v1/manage/jobs")).status_code == 403
    assert (await client.get("/v1/manage/status")).json()["token"] is None


async def test_non_ascii_management_token_rejected_not_internal_error(management_api):
    client, _ = management_api
    response = await client.get("/v1/manage/jobs", headers={b"X-Bridge-Token": b"\xff"})
    assert response.status_code == 403


@pytest.mark.parametrize("kind", ["PDF", "HWPX"])
async def test_drafts_validate_but_never_publish_and_stale_quote_rejected(management_api, kind):
    client, app = management_api
    snapshot = await seed(app, kind=kind)
    suggested = (await client.get("/v1/manage/notices/TEST/suggestions")).json()
    assert suggested["approved"] is False and len(suggested["suggestions"]) == 1
    item = suggested["suggestions"][0]
    assert item["location_kind"] == ("SECTION" if kind == "HWPX" else "PAGE")
    draft = dict(
        notice_id="TEST",
        version_hash=snapshot.version_hash,
        approved_by="synthetic-reviewer",
        scope_complete=False,
        conditions=[item["rule"]],
        citations=[item["citation"]],
    )
    assert (await client.post("/v1/manage/review/validate", json=draft)).status_code == 200
    assert await app.state.storage.publications.find_approved() == []
    draft["citations"][0]["passage"] = "존재하지 않는 인용문"
    assert (await client.post("/v1/manage/review/validate", json=draft)).status_code == 409
    await app.state.storage.notices.save(snapshot.model_copy(update={"version_hash": "b" * 64}))
    assert (await client.post("/v1/manage/review/validate", json=draft)).status_code == 409
    assert (await client.get("/v1/manage/notices/missing/suggestions")).status_code == 404


async def test_ocr_sources_cannot_be_exported_as_approved_evidence(management_api):
    client, app = management_api
    snapshot = await seed(app, ocr=True)
    assert not (await client.get("/v1/manage/notices/TEST/suggestions")).json()["suggestions"]
    evidence_id = f"TEST:{snapshot.version_hash}:region"
    draft = dict(
        notice_id="TEST",
        version_hash=snapshot.version_hash,
        approved_by="tester",
        conditions=[dict(field="hq_region", allowed_regions=["대전"], evidence_id=evidence_id)],
        citations=[
            dict(
                evidence_id=evidence_id,
                pdf_sha256="a" * 64,
                page_number=1,
                passage="본사가 대전광역시에 소재한 기업을 지원합니다.",
            )
        ],
    )
    assert (await client.post("/v1/manage/review/validate", json=draft)).status_code == 409


async def test_collection_validation_and_retry_without_api_key(management_api):
    client, app = management_api
    app.state.settings.bizinfo_api_key = None
    assert (await client.post("/v1/manage/jobs", json={})).status_code == 503
    assert (await client.post("/v1/manage/jobs", json={"count": 101})).status_code == 422
    assert (await client.post("/v1/manage/jobs", json={"notice_id": "missing"})).status_code == 404
    await seed(app)
    response = await client.post("/v1/manage/jobs", json={"notice_id": "TEST", "documents": False})
    assert response.status_code == 202
    await asyncio.gather(*app.state.collection_tasks)
    job = (await client.get("/v1/manage/jobs")).json()[0]
    assert job["status"] == "SUCCEEDED" and job["processed"] == 1
    assert job["items"] == [{"notice_id": "TEST", "status": "METADATA_STORED"}]


async def test_database_enforces_one_job_and_recovers_interrupted(management_api):
    client, app = management_api
    repo = app.state.storage.jobs
    job = CollectionJob(job_id="job_test", status="RUNNING", request=CollectionRequest())
    await repo.begin(job)
    with pytest.raises(ActiveCollectionError):
        await repo.begin(job.model_copy(update={"job_id": "job_second"}))
    await seed(app)
    assert (await client.post("/v1/manage/jobs", json={"notice_id": "TEST"})).status_code == 409
    await repo.recover()
    saved = (await repo.list())[0]
    assert saved.status == "INTERRUPTED" and saved.error_code == "SERVER_RESTARTED"
    await repo.begin(job.model_copy(update={"job_id": "job_second"}))


async def test_failed_collection_never_persists_secret_exception(management_api, monkeypatch):
    client, app = management_api
    await seed(app)

    async def broken(*args, **kwargs):
        raise RuntimeError("secret-api-key-that-must-not-leak")

    monkeypatch.setattr(app.state.storage.notices, "save", broken)
    assert (await client.post("/v1/manage/jobs", json={"notice_id": "TEST"})).status_code == 202
    await asyncio.gather(*app.state.collection_tasks)
    response = await client.get("/v1/manage/jobs")
    assert "secret-api-key" not in response.text
    assert response.json()[0]["status"] == "FAILED"


@pytest.mark.parametrize(
    "failure,expected", [(None, 200), ("changed", 409), ("parse", 502), ("pages", 422)]
)
async def test_ocr_api_hash_lock_limits_and_no_source_overwrite(
    management_api, monkeypatch, failure, expected
):
    from sme_bridge.api.routes import management
    from sme_bridge.documents.pdf import DocumentParseError
    from sme_bridge.schemas.management import OcrPage

    client, app = management_api
    snapshot = await seed(app)
    data = b"%PDF-synthetic-ocr-preview-test"
    digest = hashlib.sha256(data).hexdigest()
    await store_parsed_document(
        app.state.storage.documents,
        notice_id="TEST",
        notice_version_hash=snapshot.version_hash,
        source_url="https://www.bizinfo.go.kr/test.pdf",
        parsed=ParsedPdf(
            sha256=digest,
            page_count=1,
            ocr_required_pages=[1],
            pages=[PdfPage(page_number=1, text="", character_count=0, requires_ocr=True)],
        ),
    )
    monkeypatch.setattr(management, "ocr_available", lambda _: True)

    async def download(*args):
        if failure == "changed":
            await app.state.storage.notices.save(
                snapshot.model_copy(update={"version_hash": "b" * 64})
            )
        return data

    def preview(*args):
        if failure == "parse":
            raise DocumentParseError("synthetic failure")
        if failure == "pages":
            raise ValueError("synthetic invalid page")
        return [OcrPage(page_number=1, text="OCR 참고 문장")]

    monkeypatch.setattr(management.OfficialPdfDownloader, "download", download)
    monkeypatch.setattr(management, "preview_ocr", preview)
    await app.state.ocr_lock.acquire()
    assert (
        await client.post("/v1/manage/notices/TEST/ocr", json={"pages": [1]})
    ).status_code == 409
    app.state.ocr_lock.release()
    response = await client.post("/v1/manage/notices/TEST/ocr", json={"pages": [1]})
    assert response.status_code == expected
    assert not app.state.ocr_lock.locked()
    stored = await app.state.storage.documents.search(
        notice_id="TEST", version_hash=snapshot.version_hash
    )
    assert next(p for p in stored if p.pdf_sha256 == digest).text == ""
    assert await app.state.storage.publications.find_approved() == []


async def test_collection_shutdown_is_durable_and_releases_active_slot(management_api, monkeypatch):
    client, app = management_api
    await seed(app)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(app.state.storage.notices, "save", blocked)
    await client.post("/v1/manage/jobs", json={"notice_id": "TEST"})
    await asyncio.wait_for(entered.wait(), timeout=3)
    tasks = list(app.state.collection_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    job = (await app.state.storage.jobs.list())[0]
    assert job.status == "INTERRUPTED" and job.error_code == "SERVER_STOPPED"
    assert job.finished_at is not None
    await app.state.storage.jobs.begin(
        job.model_copy(update={"job_id": "job_new", "status": "QUEUED"})
    )


async def test_actual_restart_recovers_pending_job_and_rotates_token(tmp_path):
    settings = Settings(
        _env_file=None, storage_backend="sqlite", sqlite_path=str(tmp_path / "restart.sqlite3")
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        first_token = app.state.management_token
        await app.state.storage.jobs.begin(
            CollectionJob(job_id="job_restart", status="RUNNING", request=CollectionRequest())
        )
    restarted = create_app(settings)
    async with restarted.router.lifespan_context(restarted):
        assert restarted.state.management_token != first_token
        assert (await restarted.state.storage.jobs.list())[0].status == "INTERRUPTED"
