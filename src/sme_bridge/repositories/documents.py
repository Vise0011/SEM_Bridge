"""Repositories for parsed notice documents and page passages."""

from typing import Protocol

import asyncpg

from sme_bridge.schemas.document import DocumentPassage, ParsedPdf, StoredPassage

CREATE_DOCUMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notice_documents (
    notice_id TEXT NOT NULL,
    notice_version_hash CHAR(64) NOT NULL,
    pdf_sha256 CHAR(64) NOT NULL,
    source_url TEXT NOT NULL,
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    ocr_required_pages INTEGER[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (notice_id, notice_version_hash, pdf_sha256),
    FOREIGN KEY (notice_id, notice_version_hash)
        REFERENCES notice_versions (notice_id, version_hash)
)
"""

CREATE_PASSAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notice_passages (
    notice_id TEXT NOT NULL,
    notice_version_hash CHAR(64) NOT NULL,
    pdf_sha256 CHAR(64) NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    text TEXT NOT NULL,
    character_count INTEGER NOT NULL CHECK (character_count >= 0),
    requires_ocr BOOLEAN NOT NULL,
    trust_level TEXT NOT NULL CHECK (trust_level = 'UNTRUSTED_SOURCE'),
    security_flags TEXT[] NOT NULL,
    PRIMARY KEY (notice_id, notice_version_hash, pdf_sha256, page_number),
    FOREIGN KEY (notice_id, notice_version_hash, pdf_sha256)
        REFERENCES notice_documents (notice_id, notice_version_hash, pdf_sha256)
)
"""

CREATE_CURRENT_DOCUMENT_SQL = """
CREATE TABLE IF NOT EXISTS current_notice_documents (
    notice_id TEXT, notice_version_hash CHAR(64), pdf_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (notice_id, notice_version_hash),
    FOREIGN KEY (notice_id, notice_version_hash, pdf_sha256)
        REFERENCES notice_documents (notice_id, notice_version_hash, pdf_sha256)
)
"""

INSERT_DOCUMENT_SQL = """
INSERT INTO notice_documents (
    notice_id, notice_version_hash, pdf_sha256, source_url,
    page_count, ocr_required_pages
)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (notice_id, notice_version_hash, pdf_sha256) DO NOTHING
"""

INSERT_PASSAGE_SQL = """
INSERT INTO notice_passages (
    notice_id, notice_version_hash, pdf_sha256, page_number,
    text, character_count, requires_ocr, trust_level, security_flags, document_kind, location_kind
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (notice_id, notice_version_hash, pdf_sha256, page_number) DO NOTHING
"""


class DocumentRepository(Protocol):
    """Persistence boundary for page-aware parsed documents."""

    async def save(
        self,
        *,
        notice_id: str,
        notice_version_hash: str,
        source_url: str,
        parsed: ParsedPdf,
        passages: list[DocumentPassage],
    ) -> bool:
        """Return True only when a new document hash is inserted."""
        ...

    async def search(
        self,
        *,
        notice_id: str,
        version_hash: str,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredPassage]: ...

    async def current_hash(self, notice_id: str, version_hash: str) -> str | None: ...


class InMemoryDocumentRepository:
    """Deterministic document repository used in tests."""

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str, str], ParsedPdf] = {}
        self.passages: dict[tuple[str, str, str], list[DocumentPassage]] = {}
        self.urls: dict[tuple[str, str, str], str] = {}
        self.current: dict[tuple[str, str], str] = {}

    async def save(
        self,
        *,
        notice_id: str,
        notice_version_hash: str,
        source_url: str,
        parsed: ParsedPdf,
        passages: list[DocumentPassage],
    ) -> bool:
        key = (notice_id, notice_version_hash, parsed.sha256)
        is_new = key not in self.documents
        self.documents.setdefault(key, parsed)
        self.passages.setdefault(key, list(passages))
        self.urls.setdefault(key, source_url)
        self.current[key[:2]] = parsed.sha256
        return is_new

    async def search(
        self,
        *,
        notice_id: str,
        version_hash: str,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredPassage]:
        items = [
            StoredPassage(
                **passage.model_dump(),
                notice_id=notice_id,
                notice_version_hash=version_hash,
                pdf_sha256=key[2],
                source_url=self.urls[key],
            )
            for key, passages in sorted(self.passages.items())
            if key[:2] == (notice_id, version_hash)
            for passage in passages
            if query.casefold() in passage.text.casefold()
        ]
        return items[offset : offset + limit]

    async def current_hash(self, notice_id: str, version_hash: str) -> str | None:
        return self.current.get((notice_id, version_hash))


class PostgresDocumentRepository:
    """PostgreSQL implementation for immutable page-level document data."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(CREATE_DOCUMENTS_TABLE_SQL)
                await connection.execute(CREATE_PASSAGES_TABLE_SQL)
                await connection.execute(
                    "ALTER TABLE notice_passages ADD COLUMN IF NOT EXISTS "
                    "document_kind TEXT NOT NULL DEFAULT 'PDF'"
                )
                await connection.execute(
                    "ALTER TABLE notice_passages ADD COLUMN IF NOT EXISTS "
                    "location_kind TEXT NOT NULL DEFAULT 'PAGE'"
                )
                await connection.execute(CREATE_CURRENT_DOCUMENT_SQL)

    async def save(
        self,
        *,
        notice_id: str,
        notice_version_hash: str,
        source_url: str,
        parsed: ParsedPdf,
        passages: list[DocumentPassage],
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    INSERT_DOCUMENT_SQL,
                    notice_id,
                    notice_version_hash,
                    parsed.sha256,
                    source_url,
                    parsed.page_count,
                    parsed.ocr_required_pages,
                )
                await connection.executemany(
                    INSERT_PASSAGE_SQL,
                    [
                        (
                            notice_id,
                            notice_version_hash,
                            parsed.sha256,
                            passage.page_number,
                            passage.text,
                            passage.character_count,
                            passage.requires_ocr,
                            passage.trust_level,
                            [flag.value for flag in passage.security_flags],
                            passage.document_kind,
                            passage.location_kind,
                        )
                        for passage in passages
                    ],
                )
                await connection.execute(
                    """INSERT INTO current_notice_documents VALUES ($1,$2,$3)
                    ON CONFLICT (notice_id, notice_version_hash)
                    DO UPDATE SET pdf_sha256=EXCLUDED.pdf_sha256""",
                    notice_id,
                    notice_version_hash,
                    parsed.sha256,
                )
        return str(result) == "INSERT 0 1"

    async def search(
        self,
        *,
        notice_id: str,
        version_hash: str,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredPassage]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT p.*, d.source_url FROM notice_passages p
                JOIN notice_documents d USING (notice_id, notice_version_hash, pdf_sha256)
                WHERE p.notice_id=$1 AND p.notice_version_hash=$2
                    AND position(lower($3) in lower(p.text)) > 0
                ORDER BY p.pdf_sha256, p.page_number LIMIT $4 OFFSET $5""",
                notice_id,
                version_hash,
                query,
                limit,
                offset,
            )
        return [StoredPassage.model_validate(dict(row)) for row in rows]

    async def current_hash(self, notice_id: str, version_hash: str) -> str | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                """SELECT pdf_sha256 FROM current_notice_documents
                WHERE notice_id=$1 AND notice_version_hash=$2""",
                notice_id,
                version_hash,
            )
        return None if value is None else str(value)
