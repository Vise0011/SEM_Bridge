"""Immutable human approvals; stale notice versions are excluded from evaluation."""

import hashlib

import asyncpg

from sme_bridge.repositories.documents import PostgresDocumentRepository
from sme_bridge.repositories.programs import InMemoryProgramRepository
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.schemas.publication import PublishedProgram

CREATE_PUBLICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS program_publications (
    approval_hash CHAR(64) PRIMARY KEY,
    notice_id TEXT NOT NULL,
    version_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (notice_id, version_hash) REFERENCES notice_versions (notice_id, version_hash)
)
"""


class PostgresPublicationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(CREATE_PUBLICATIONS_SQL)

    async def publish(self, publication: PublishedProgram) -> None:
        payload = publication.model_dump_json()
        version = (publication.definition.notice_version or "").removeprefix("sha256:")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                current = await connection.fetchval(
                    "SELECT current_version_hash FROM notices WHERE notice_id=$1 FOR UPDATE",
                    publication.definition.program_id,
                )
                if current != version:
                    raise ValueError("Notice changed during review; approve the current version")
                current_pdf = await connection.fetchval(
                    """SELECT pdf_sha256 FROM current_notice_documents
                    WHERE notice_id=$1 AND notice_version_hash=$2 FOR SHARE""",
                    publication.definition.program_id,
                    version,
                )
                if not current_pdf or any(
                    e.pdf_sha256 != current_pdf for e in publication.evidence
                ):
                    raise ValueError("PDF changed during review; approve the current PDF")
                await connection.execute(
                    """INSERT INTO program_publications
                    (approval_hash, notice_id, version_hash, payload)
                    VALUES ($1,$2,$3,$4::jsonb) ON CONFLICT DO NOTHING""",
                    hashlib.sha256(payload.encode()).hexdigest(),
                    publication.definition.program_id,
                    version,
                    payload,
                )

    async def _publications(self) -> list[PublishedProgram]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT DISTINCT ON (p.notice_id) p.payload FROM program_publications p
                JOIN notices n ON n.notice_id=p.notice_id AND n.current_version_hash=p.version_hash
                ORDER BY p.notice_id, p.approved_at DESC, p.approval_hash"""
            )
        publications = [PublishedProgram.model_validate_json(row["payload"]) for row in rows]
        current: list[PublishedProgram] = []
        documents = PostgresDocumentRepository(self._pool)
        for item in publications:
            version = (item.definition.notice_version or "").removeprefix("sha256:")
            pdf_hash = await documents.current_hash(item.definition.program_id, version)
            if pdf_hash and all(e.pdf_sha256 == pdf_hash for e in item.evidence):
                current.append(item)
        return current

    async def find_approved(self) -> list[ProgramDefinition]:
        return [item.definition for item in await self._publications()]

    async def find_candidates(
        self,
        profile: BusinessProfile,
        limit: int = 3,
    ) -> list[ProgramDefinition]:
        repo = InMemoryProgramRepository(await self.find_approved())
        return await repo.find_candidates(profile, limit)

    async def find_evidence(self, evidence_ids: list[str]) -> list[EvidenceReference]:
        wanted = set(evidence_ids)
        return [
            evidence
            for item in await self._publications()
            for evidence in item.evidence
            if evidence.evidence_id in wanted
        ]
