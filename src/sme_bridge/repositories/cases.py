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
INSERT INTO cases (case_id, status, profile, programs)
VALUES ($1, $2, $3::jsonb, $4::jsonb)
"""


class CaseRepository(Protocol):
    """Storage boundary required by case intake."""

    async def save(self, case: CaseCreated) -> None:
        """Persist one evaluated case."""
        ...

    async def find(self, case_id: str) -> CaseCreated | None:
        """Return one persisted case, or None when it does not exist."""
        ...


class InMemoryCaseRepository:
    """Small deterministic repository used by unit tests."""

    def __init__(self) -> None:
        self.items: dict[str, CaseCreated] = {}

    async def save(self, case: CaseCreated) -> None:
        self.items[case.case_id] = case

    async def find(self, case_id: str) -> CaseCreated | None:
        return self.items.get(case_id)


class PostgresCaseRepository:
    """PostgreSQL repository storing validated snapshots as JSONB."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(CREATE_CASES_TABLE_SQL)

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
            )

    async def find(self, case_id: str) -> CaseCreated | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT case_id, status, profile::text AS profile, "
                "programs::text AS programs "
                "FROM cases WHERE case_id = $1",
                case_id,
            )
        if row is None:
            return None
        return CaseCreated.model_validate(
            {
                "case_id": row["case_id"],
                "status": row["status"],
                "profile": json.loads(row["profile"]),
                "programs": json.loads(row["programs"]),
            }
        )
