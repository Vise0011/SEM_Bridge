"""Run against an isolated temporary PostgreSQL schema when a test DSN is supplied."""

import os
from uuid import uuid4

import asyncpg
import pytest

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.repositories.cases import IdempotencyConflict, PostgresCaseRepository
from sme_bridge.repositories.documents import PostgresDocumentRepository
from sme_bridge.repositories.notices import PostgresNoticeRepository
from sme_bridge.repositories.publications import PostgresPublicationRepository
from sme_bridge.schemas.case import CaseCreated, CaseStatus
from sme_bridge.schemas.document import ParsedPdf, PdfPage
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.publication import PublicationDraft
from sme_bridge.services.documents import store_parsed_document
from sme_bridge.services.ingestion import build_notice_snapshot
from sme_bridge.services.publication import verify_publication


async def test_postgres_full_persistence_and_current_version_gate() -> None:
    dsn = os.environ.get("SME_BRIDGE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration requires SME_BRIDGE_TEST_POSTGRES_DSN")
    schema = "test_bridge_" + uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=3, server_settings={"search_path": schema}
    )
    try:
        notices, documents = PostgresNoticeRepository(pool), PostgresDocumentRepository(pool)
        cases, publications = PostgresCaseRepository(pool), PostgresPublicationRepository(pool)
        await notices.ensure_schema()
        await documents.ensure_schema()
        await cases.ensure_schema()
        await publications.ensure_schema()
        snapshot = build_notice_snapshot(
            BizinfoNotice.model_validate(
                {
                    "pblancId": "PBLN_TEST",
                    "pblancNm": "대전 공고",
                    "pblancUrl": "/example",
                }
            )
        )
        assert await notices.save(snapshot)
        assert not await notices.save(snapshot)
        assert len(await notices.list_current(query="대전")) == 1
        text = "대전 지역의 기업을 지원합니다."
        parsed = ParsedPdf(
            sha256="a" * 64,
            page_count=1,
            ocr_required_pages=[],
            pages=[
                PdfPage(page_number=1, text=text, character_count=len(text), requires_ocr=False)
            ],
        )
        assert await store_parsed_document(
            documents,
            notice_id=snapshot.notice_id,
            notice_version_hash=snapshot.version_hash,
            source_url="https://www.bizinfo.go.kr/example.pdf",
            parsed=parsed,
        )
        evidence_id = f"PBLN_TEST:{snapshot.version_hash}:region"
        draft = PublicationDraft.model_validate(
            {
                "notice_id": snapshot.notice_id,
                "version_hash": snapshot.version_hash,
                "approved_by": "test-reviewer",
                "scope_complete": False,
                "conditions": [
                    {"field": "hq_region", "allowed_regions": ["대전"], "evidence_id": evidence_id}
                ],
                "citations": [
                    {
                        "evidence_id": evidence_id,
                        "pdf_sha256": "a" * 64,
                        "page_number": 1,
                        "passage": text,
                    }
                ],
            }
        )
        publication = await verify_publication(draft, notices, documents)
        await publications.publish(publication)
        assert len(await publications.find_approved()) == 1
        case = CaseCreated(
            case_id="case_test",
            status=CaseStatus.REVIEW_PENDING,
            source="official",
            notes=["검토 필요"],
            programs=[],
            profile=BusinessProfile.model_validate(
                {"business_type": "CORPORATION", "query_date": "2026-10-07"}
            ),
        )
        await cases.save_idempotent(case, "key-1", "b" * 64)
        assert await cases.find(case.case_id) == case
        assert await cases.save_idempotent(case, "key-1", "b" * 64) == case
        with pytest.raises(IdempotencyConflict):
            await cases.save_idempotent(case, "key-1", "c" * 64)
        changed = snapshot.model_copy(update={"version_hash": "d" * 64})
        await notices.save(changed)
        assert await publications.find_approved() == []
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
