"""Durable collection outcomes with a database-enforced single active job."""

from typing import Protocol

import asyncpg

from sme_bridge.repositories.sqlite import SQLiteStore
from sme_bridge.schemas.management import CollectionJob

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_jobs(
  job_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, started_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_collection
  ON collection_jobs((1)) WHERE status IN ('QUEUED','RUNNING');
"""
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_jobs(
  job_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload JSONB NOT NULL,
  started_at TIMESTAMPTZ NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_collection
  ON collection_jobs((1)) WHERE status IN ('QUEUED','RUNNING');
"""


class ActiveCollectionError(ValueError):
    pass


class JobRepository(Protocol):
    async def begin(self, job: CollectionJob) -> None: ...
    async def save(self, job: CollectionJob) -> None: ...
    async def list(self) -> list[CollectionJob]: ...
    async def recover(self) -> None: ...


class SQLiteJobRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def ensure_schema(self) -> None:
        await self.store.run(lambda c: c.executescript(SQLITE_SCHEMA) and None)

    async def begin(self, job: CollectionJob) -> None:
        import sqlite3

        try:
            await self.store.run(
                lambda c: (
                    c.execute(
                        "INSERT INTO collection_jobs VALUES(?,?,?,?)",
                        (job.job_id, job.status, job.model_dump_json(), job.started_at.isoformat()),
                    )
                    and None
                )
            )
        except sqlite3.IntegrityError as exc:
            raise ActiveCollectionError("Collection already running") from exc

    async def save(self, job: CollectionJob) -> None:
        await self.store.run(
            lambda c: (
                c.execute(
                    "UPDATE collection_jobs SET status=?,payload=? WHERE job_id=?",
                    (job.status, job.model_dump_json(), job.job_id),
                )
                and None
            )
        )

    async def list(self) -> list[CollectionJob]:
        rows = await self.store.run(
            lambda c: c.execute(
                "SELECT payload FROM collection_jobs ORDER BY started_at DESC LIMIT 30"
            ).fetchall()
        )
        return [CollectionJob.model_validate_json(row[0]) for row in rows]

    async def recover(self) -> None:
        for job in await self.list():
            if job.status in {"QUEUED", "RUNNING"}:
                job.status = "INTERRUPTED"
                job.error_code = "SERVER_RESTARTED"
                await self.save(job)


class PostgresJobRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute(PG_SCHEMA)

    async def begin(self, job: CollectionJob) -> None:
        async with self.pool.acquire() as c:
            try:
                await c.execute(
                    "INSERT INTO collection_jobs VALUES($1,$2,$3::jsonb,$4)",
                    job.job_id,
                    job.status,
                    job.model_dump_json(),
                    job.started_at,
                )
            except asyncpg.UniqueViolationError as exc:
                raise ActiveCollectionError("Collection already running") from exc

    async def save(self, job: CollectionJob) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE collection_jobs SET status=$1,payload=$2::jsonb WHERE job_id=$3",
                job.status,
                job.model_dump_json(),
                job.job_id,
            )

    async def list(self) -> list[CollectionJob]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                "SELECT payload FROM collection_jobs ORDER BY started_at DESC LIMIT 30"
            )
        return [CollectionJob.model_validate_json(row["payload"]) for row in rows]

    async def recover(self) -> None:
        for job in await self.list():
            if job.status in {"QUEUED", "RUNNING"}:
                job.status = "INTERRUPTED"
                job.error_code = "SERVER_RESTARTED"
                await self.save(job)
