"""Persistence repositories."""

from sme_bridge.repositories.cases import (
    CaseRepository,
    InMemoryCaseRepository,
    PostgresCaseRepository,
)
from sme_bridge.repositories.documents import (
    DocumentRepository,
    InMemoryDocumentRepository,
    PostgresDocumentRepository,
)
from sme_bridge.repositories.notices import (
    InMemoryNoticeRepository,
    NoticeRepository,
    PostgresNoticeRepository,
)
from sme_bridge.repositories.programs import (
    InMemoryProgramRepository,
    Neo4jProgramRepository,
    ProgramRepository,
)

__all__ = [
    "CaseRepository",
    "DocumentRepository",
    "InMemoryCaseRepository",
    "InMemoryProgramRepository",
    "InMemoryNoticeRepository",
    "InMemoryDocumentRepository",
    "Neo4jProgramRepository",
    "PostgresCaseRepository",
    "PostgresNoticeRepository",
    "PostgresDocumentRepository",
    "ProgramRepository",
    "NoticeRepository",
]
