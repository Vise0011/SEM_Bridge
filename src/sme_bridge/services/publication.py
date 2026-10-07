"""Verify the source before accepting a human-reviewed publication."""

from sme_bridge.repositories.documents import DocumentRepository
from sme_bridge.repositories.notices import NoticeRepository
from sme_bridge.schemas.evidence import EvidenceReference, SourceKind
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.schemas.publication import PublicationDraft, PublishedProgram


async def verify_publication(
    draft: PublicationDraft,
    notices: NoticeRepository,
    documents: DocumentRepository,
) -> PublishedProgram:
    record = await notices.find(draft.notice_id)
    if record is None or record.snapshot.version_hash != draft.version_hash:
        raise ValueError("Only the current stored notice version can be approved")
    evidence: list[EvidenceReference] = []
    current_pdf = await documents.current_hash(draft.notice_id, draft.version_hash)
    for citation in draft.citations:
        if current_pdf != citation.pdf_sha256:
            raise ValueError("Only the currently downloaded PDF can be approved")
        pages = await documents.search(
            notice_id=draft.notice_id,
            version_hash=draft.version_hash,
            query=citation.passage,
            limit=100,
        )
        page = next(
            (
                item
                for item in pages
                if item.pdf_sha256 == citation.pdf_sha256
                and item.page_number == citation.page_number
            ),
            None,
        )
        if page is None or citation.passage not in page.text:
            raise ValueError("Citation does not exactly match its stored PDF page")
        if page.requires_ocr or page.security_flags:
            raise ValueError(
                "OCR or security-flagged pages require separate review before approval"
            )
        evidence.append(
            EvidenceReference(
                evidence_id=citation.evidence_id,
                passage=citation.passage,
                page=citation.page_number,
                source_url=page.source_url,
                notice_version=f"sha256:{draft.version_hash}",
                source_kind=SourceKind.OFFICIAL_NOTICE,
                pdf_sha256=citation.pdf_sha256,
            )
        )
    return PublishedProgram(
        definition=ProgramDefinition(
            program_id=draft.notice_id,
            title=record.snapshot.title,
            conditions=draft.conditions,
            source_kind=SourceKind.OFFICIAL_NOTICE,
            notice_version=f"sha256:{draft.version_hash}",
            scope_complete=draft.scope_complete,
        ),
        evidence=evidence,
        approved_by=draft.approved_by,
    )
