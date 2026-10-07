"""Persistence implementations for eligibility cases."""

import json
from typing import Protocol

import asyncpg

from sme_bridge.schemas.case import CaseCreated

CREATE_CASES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    profile JSONB NOT NULL,
    programs JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

INSERT_CASE_SQL = """
INSERT INTO cases (case_id, status, profile, programs, snapshot)
VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb)
"""


class IdempotencyConflict(ValueError):
    """A retry key was reused for a different request."""


class CaseRepository(Protocol):
    """Storage boundary required by case intake."""

    async def save(self, case: CaseCreated) -> None:
        """Persist one evaluated case."""
        ...

    async def save_idempotent(
        self,
        case: CaseCreated,
        key: str,
        input_hash: str,
    ) -> CaseCreated: ...

    async def find(self, case_id: str) -> CaseCreated | None:
        """Return one persisted case, or None when it does not exist."""
        ...


class InMemoryCaseRepository:
    """Small deterministic repository used by unit tests."""

    def __init__(self) -> None:
        self.items: dict[str, CaseCreated] = {}
        self.requests: dict[str, tuple[str, str]] = {}

    async def save(self, case: CaseCreated) -> None:
        self.items[case.case_id] = case

    async def find(self, case_id: str) -> CaseCreated | None:
        return self.items.get(case_id)

    async def save_idempotent(
        self,
        case: CaseCreated,
        key: str,
        input_hash: str,
    ) -> CaseCreated:
        previous = self.requests.get(key)
        if previous is not None:
            if previous[0] != input_hash:
                raise IdempotencyConflict("Retry key was reused for a different request")
            return self.items[previous[1]]
        self.items[case.case_id] = case
        self.requests[key] = (input_hash, case.case_id)
        return case


class PostgresCaseRepository:
    """PostgreSQL repository storing validated snapshots as JSONB."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(CREATE_CASES_TABLE_SQL)
            await connection.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS snapshot JSONB")
            await connection.execute("""CREATE TABLE IF NOT EXISTS case_requests (
                request_key TEXT PRIMARY KEY, input_hash CHAR(64) NOT NULL,
                case_id TEXT NOT NULL REFERENCES cases(case_id))""")

    async def save(self, case: CaseCreated) -> None:
        profile_json = case.profile.model_dump_json()
        programs_json = json.dumps(
            [program.model_dump(mode="json") for program in case.programs],
            ensure_ascii=False,
        )
        async with self._pool.acquire() as connection:
            await connection.execute(
                INSERT_CASE_SQL,
                case.case_id,
                case.status.value,
                profile_json,
                programs_json,
                case.model_dump_json(),
            )

    async def find(self, case_id: str) -> CaseCreated | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT case_id, status, profile::text AS profile, "
                "programs::text AS programs, snapshot::text AS snapshot "
                "FROM cases WHERE case_id = $1",
                case_id,
            )
        if row is None:
            return None
        if row["snapshot"] is not None:
            return CaseCreated.model_validate_json(row["snapshot"])
        return CaseCreated.model_validate(
            {
                "case_id": row["case_id"],
                "status": row["status"],
                "profile": json.loads(row["profile"]),
                "programs": json.loads(row["programs"]),
            }
        )

    async def save_idempotent(
        self,
        case: CaseCreated,
        key: str,
        input_hash: str,
    ) -> CaseCreated:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", key
                )
                previous = await connection.fetchrow(
                    """SELECT r.input_hash,c.snapshot FROM case_requests r
                    JOIN cases c USING(case_id) WHERE r.request_key=$1""",
                    key,
                )
                if previous is not None:
                    if previous["input_hash"] != input_hash:
                        raise IdempotencyConflict("Retry key was reused for a different request")
                    return CaseCreated.model_validate_json(previous["snapshot"])
                await connection.execute(
                    INSERT_CASE_SQL,
                    case.case_id,
                    case.status.value,
                    case.profile.model_dump_json(),
                    json.dumps([p.model_dump(mode="json") for p in case.programs]),
                    case.model_dump_json(),
                )
                await connection.execute(
                    "INSERT INTO case_requests VALUES($1,$2,$3)", key, input_hash, case.case_id
                )
        return case
