"""Preparation and persistence of untrusted PDF page text."""

import asyncio
from typing import Protocol

from sme_bridge.documents import parse_pdf
from sme_bridge.documents.hwpx import parse_hwpx
from sme_bridge.repositories.documents import DocumentRepository
from sme_bridge.schemas.document import (
    DocumentIngestionResult,
    DocumentPassage,
    ParsedPdf,
)
from sme_bridge.schemas.notice import NoticeSnapshot
from sme_bridge.security import sanitize_untrusted_text


class PdfSource(Protocol):
    """Minimal downloader contract needed by document ingestion."""

    async def download(self, url: str) -> bytes: ...


def prepare_passages(parsed: ParsedPdf) -> list[DocumentPassage]:
    """Normalize pages while preserving explicit untrusted-source metadata."""
    passages: list[DocumentPassage] = []
    for page in parsed.pages:
        sanitized = sanitize_untrusted_text(page.text)
        passages.append(
            DocumentPassage(
                page_number=page.page_number,
                text=sanitized.text,
                character_count=len(sanitized.text),
                requires_ocr=page.requires_ocr,
                document_kind=page.document_kind,
                location_kind=page.location_kind,
                trust_level=sanitized.trust_level,
                security_flags=sanitized.security_flags,
            )
        )
    return passages


async def store_parsed_document(
    repository: DocumentRepository,
    *,
    notice_id: str,
    notice_version_hash: str,
    source_url: str,
    parsed: ParsedPdf,
) -> bool:
    """Prepare and atomically store one parsed notice document."""
    return await repository.save(
        notice_id=notice_id,
        notice_version_hash=notice_version_hash,
        source_url=source_url,
        parsed=parsed,
        passages=prepare_passages(parsed),
    )


async def ingest_notice_document(
    snapshot: NoticeSnapshot,
    downloader: PdfSource,
    repository: DocumentRepository,
) -> DocumentIngestionResult:
    """Run the complete attachment pipeline for one immutable notice version."""
    if not snapshot.attachment_url.strip():
        return DocumentIngestionResult(
            notice_id=snapshot.notice_id,
            status="NO_ATTACHMENT",
        )

    data = await downloader.download(snapshot.attachment_url)
    parsed = await asyncio.to_thread(parse_pdf if data.startswith(b"%PDF-") else parse_hwpx, data)
    passages = prepare_passages(parsed)
    inserted = await repository.save(
        notice_id=snapshot.notice_id,
        notice_version_hash=snapshot.version_hash,
        source_url=snapshot.attachment_url,
        parsed=parsed,
        passages=passages,
    )
    return DocumentIngestionResult(
        notice_id=snapshot.notice_id,
        status="STORED" if inserted else "UNCHANGED",
        pdf_sha256=parsed.sha256,
        page_count=parsed.page_count,
        ocr_required_pages=parsed.ocr_required_pages,
        flagged_pages=sum(bool(passage.security_flags) for passage in passages),
    )
