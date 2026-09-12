"""Fetch and persist one bounded batch of official Bizinfo finance notices."""

import asyncio
import sys

import asyncpg

from sme_bridge.clients import BizinfoClient, BizinfoClientError
from sme_bridge.config import get_settings
from sme_bridge.repositories import PostgresNoticeRepository
from sme_bridge.services.ingestion import ingest_finance_notices


async def main() -> int:
    settings = get_settings()
    api_key = settings.bizinfo_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        print("BIZINFO_API_KEY is missing from .env.", file=sys.stderr)
        return 1

    try:
        pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=2,
        )
    except (OSError, asyncpg.PostgresError):
        print("PostgreSQL is unavailable. Start the container first.", file=sys.stderr)
        return 1

    try:
        repository = PostgresNoticeRepository(pool)
        await repository.ensure_schema()
        async with BizinfoClient(api_key.get_secret_value()) as client:
            report = await ingest_finance_notices(client, repository, count=30)
    except BizinfoClientError:
        print("Bizinfo ingestion failed. Check the API key and network.", file=sys.stderr)
        return 1
    finally:
        await pool.close()

    print(
        f"Bizinfo ingestion: fetched={report.fetched}, "
        f"new_versions={report.new_versions}, unchanged={report.unchanged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
