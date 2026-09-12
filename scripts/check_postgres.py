"""Verify PostgreSQL connectivity and initialize the local schema."""

import asyncio
import sys

import asyncpg

from sme_bridge.config import get_settings
from sme_bridge.repositories import (
    PostgresCaseRepository,
    PostgresDocumentRepository,
    PostgresNoticeRepository,
)


async def main() -> int:
    settings = get_settings()
    try:
        pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=1,
        )
    except (OSError, asyncpg.PostgresError):
        print(
            "PostgreSQL connection failed. Run 'docker compose up -d postgres' first.",
            file=sys.stderr,
        )
        return 1

    try:
        repository = PostgresCaseRepository(pool)
        await repository.ensure_schema()
        notice_repository = PostgresNoticeRepository(pool)
        await notice_repository.ensure_schema()
        document_repository = PostgresDocumentRepository(pool)
        await document_repository.ensure_schema()
        print("PostgreSQL connection, cases, notices, and document tables: OK")
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
