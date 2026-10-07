"""A concurrent retry must create one durable case; changed input must conflict."""

import asyncio
from pathlib import Path

import httpx

from sme_bridge.api.routes.cases import demo_program_repository
from sme_bridge.main import create_app
from sme_bridge.repositories import InMemoryNoticeRepository, InMemoryProgramRepository
from sme_bridge.repositories.sqlite import SQLiteCaseRepository, SQLiteStore


async def test_concurrent_retry_returns_same_case_and_rejects_changed_input(tmp_path: Path) -> None:
    store = SQLiteStore(str(tmp_path / "retry.sqlite3"))
    await store.ensure_schema()
    app = create_app()
    app.state.case_repository = SQLiteCaseRepository(store)
    app.state.program_repository = demo_program_repository
    app.state.official_program_repository = InMemoryProgramRepository([])
    app.state.notice_repository = InMemoryNoticeRepository()
    profile = {"business_type": "CORPORATION", "query_date": "2026-10-07"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        responses = await asyncio.gather(
            *[
                c.post(
                    "/v1/cases?source=demo", json=profile, headers={"Idempotency-Key": "request-1"}
                )
                for _ in range(8)
            ]
        )
        assert all(response.status_code == 201 for response in responses)
        assert len({response.json()["case_id"] for response in responses}) == 1
        response = await c.post(
            "/v1/cases?source=demo",
            json={**profile, "hq_region": "대전"},
            headers={"Idempotency-Key": "request-1"},
        )
        assert response.status_code == 409
    count = await store.run(
        lambda connection: connection.execute("SELECT count(*) FROM cases").fetchone()[0]
    )
    assert count == 1
