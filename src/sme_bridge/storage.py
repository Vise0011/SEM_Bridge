"""Shared initialization for the API and ingestion/review commands."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import asyncpg

from sme_bridge.config import Settings
from sme_bridge.repositories import CaseRepository, DocumentRepository, NoticeRepository
from sme_bridge.repositories.cases import PostgresCaseRepository
from sme_bridge.repositories.documents import PostgresDocumentRepository
from sme_bridge.repositories.notices import PostgresNoticeRepository
from sme_bridge.repositories.programs import ProgramRepository
from sme_bridge.repositories.publications import PostgresPublicationRepository
from sme_bridge.repositories.sqlite import (
    SQLiteCaseRepository,
    SQLiteDocumentRepository,
    SQLiteNoticeRepository,
    SQLitePublicationRepository,
    SQLiteStore,
)
from sme_bridge.schemas.publication import PublishedProgram


class PublicationRepository(ProgramRepository, Protocol):
    async def publish(self, publication: PublishedProgram) -> None: ...


@dataclass
class Storage:
    cases: CaseRepository
    notices: NoticeRepository
    documents: DocumentRepository
    publications: PublicationRepository


@asynccontextmanager
async def open_storage(settings: Settings) -> AsyncIterator[Storage]:
    if settings.storage_backend == "sqlite":
        store = SQLiteStore(settings.sqlite_path)
        await store.ensure_schema()
        yield Storage(
            SQLiteCaseRepository(store),
            SQLiteNoticeRepository(store),
            SQLiteDocumentRepository(store),
            SQLitePublicationRepository(store),
        )
        return
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
    try:
        cases = PostgresCaseRepository(pool)
        notices = PostgresNoticeRepository(pool)
        documents = PostgresDocumentRepository(pool)
        publications = PostgresPublicationRepository(pool)
        await cases.ensure_schema()
        await notices.ensure_schema()
        await documents.ensure_schema()
        await publications.ensure_schema()
        yield Storage(cases, notices, documents, publications)
    finally:
        await pool.close()
