"""Repositories for immutable support-notice versions."""

from datetime import UTC, datetime
from typing import Protocol

import asyncpg

from sme_bridge.schemas.notice import NoticeRecord, NoticeSnapshot

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

    async def list_current(
        self, *, query: str = "", limit: int = 30, offset: int = 0
    ) -> list[NoticeRecord]: ...

    async def find(
        self, notice_id: str, version_hash: str | None = None
    ) -> NoticeRecord | None: ...

    async def list_versions(self, notice_id: str) -> list[NoticeRecord]: ...


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

    async def list_current(
        self, *, query: str = "", limit: int = 30, offset: int = 0
    ) -> list[NoticeRecord]:
        values = sorted(self.current.values(), key=lambda item: item.notice_id, reverse=True)
        values = [item for item in values if query.casefold() in item.title.casefold()]
        return [
            NoticeRecord(snapshot=item, fetched_at=datetime.now(UTC))
            for item in values[offset : offset + limit]
        ]

    async def find(self, notice_id: str, version_hash: str | None = None) -> NoticeRecord | None:
        item = (
            self.current.get(notice_id)
            if version_hash is None
            else self.versions.get((notice_id, version_hash))
        )
        return None if item is None else NoticeRecord(snapshot=item, fetched_at=datetime.now(UTC))

    async def list_versions(self, notice_id: str) -> list[NoticeRecord]:
        return [
            NoticeRecord(snapshot=item, fetched_at=datetime.now(UTC))
            for (identifier, _), item in self.versions.items()
            if identifier == notice_id
        ]


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

    async def list_current(
        self, *, query: str = "", limit: int = 30, offset: int = 0
    ) -> list[NoticeRecord]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT v.payload, v.fetched_at FROM notices n
                JOIN notice_versions v ON v.notice_id=n.notice_id
                    AND v.version_hash=n.current_version_hash
                WHERE position(lower($1) in lower(n.title)) > 0
                ORDER BY n.updated_at DESC, n.notice_id LIMIT $2 OFFSET $3""",
                query,
                limit,
                offset,
            )
        return [
            NoticeRecord(
                snapshot=NoticeSnapshot.model_validate_json(row["payload"]),
                fetched_at=row["fetched_at"],
            )
            for row in rows
        ]

    async def find(self, notice_id: str, version_hash: str | None = None) -> NoticeRecord | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT v.payload, v.fetched_at FROM notice_versions v
                WHERE v.notice_id=$1 AND v.version_hash=COALESCE($2,
                    (SELECT current_version_hash FROM notices WHERE notice_id=$1))""",
                notice_id,
                version_hash,
            )
        return (
            None
            if row is None
            else NoticeRecord(
                snapshot=NoticeSnapshot.model_validate_json(row["payload"]),
                fetched_at=row["fetched_at"],
            )
        )

    async def list_versions(self, notice_id: str) -> list[NoticeRecord]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT payload, fetched_at FROM notice_versions WHERE notice_id=$1
                ORDER BY fetched_at DESC, version_hash LIMIT 100""",
                notice_id,
            )
        return [
            NoticeRecord(
                snapshot=NoticeSnapshot.model_validate_json(row["payload"]),
                fetched_at=row["fetched_at"],
            )
            for row in rows
        ]
