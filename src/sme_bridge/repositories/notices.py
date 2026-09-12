"""Repositories for immutable support-notice versions."""

from typing import Protocol

import asyncpg

from sme_bridge.schemas.notice import NoticeSnapshot

CREATE_NOTICE_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notice_versions (
    notice_id TEXT NOT NULL,
    version_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (notice_id, version_hash)
)
"""

CREATE_NOTICES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    current_version_hash CHAR(64) NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

INSERT_VERSION_SQL = """
INSERT INTO notice_versions (notice_id, version_hash, payload, source_url)
VALUES ($1, $2, $3::jsonb, $4)
ON CONFLICT (notice_id, version_hash) DO NOTHING
"""

UPSERT_CURRENT_NOTICE_SQL = """
INSERT INTO notices (notice_id, current_version_hash, title, source_url)
VALUES ($1, $2, $3, $4)
ON CONFLICT (notice_id) DO UPDATE
SET current_version_hash = EXCLUDED.current_version_hash,
    title = EXCLUDED.title,
    source_url = EXCLUDED.source_url,
    updated_at = NOW()
"""


class NoticeRepository(Protocol):
    """Persistence boundary for versioned notices."""

    async def save(self, snapshot: NoticeSnapshot) -> bool:
        """Return True only when a new immutable version is inserted."""
        ...


class InMemoryNoticeRepository:
    """Deterministic notice repository for unit tests."""

    def __init__(self) -> None:
        self.versions: dict[tuple[str, str], NoticeSnapshot] = {}
        self.current: dict[str, NoticeSnapshot] = {}

    async def save(self, snapshot: NoticeSnapshot) -> bool:
        key = (snapshot.notice_id, snapshot.version_hash)
        is_new = key not in self.versions
        self.versions.setdefault(key, snapshot)
        self.current[snapshot.notice_id] = snapshot
        return is_new


class PostgresNoticeRepository:
    """PostgreSQL implementation preserving every distinct notice version."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(CREATE_NOTICE_VERSIONS_TABLE_SQL)
                await connection.execute(CREATE_NOTICES_TABLE_SQL)

    async def save(self, snapshot: NoticeSnapshot) -> bool:
        payload = snapshot.model_dump_json()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    INSERT_VERSION_SQL,
                    snapshot.notice_id,
                    snapshot.version_hash,
                    payload,
                    snapshot.url,
                )
                await connection.execute(
                    UPSERT_CURRENT_NOTICE_SQL,
                    snapshot.notice_id,
                    snapshot.version_hash,
                    snapshot.title,
                    snapshot.url,
                )
        return str(result) == "INSERT 0 1"
