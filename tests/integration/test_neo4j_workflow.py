"""Verify demo graph retrieval against an explicitly configured test database."""

import os

import pytest
from neo4j import AsyncGraphDatabase

from sme_bridge.repositories.programs import Neo4jProgramRepository
from sme_bridge.schemas.profile import BusinessProfile


async def test_neo4j_demo_graph_returns_rules_and_synthetic_evidence() -> None:
    uri = os.environ.get("SME_BRIDGE_TEST_NEO4J_URI")
    if not uri:
        pytest.skip("Neo4j integration requires SME_BRIDGE_TEST_NEO4J_URI")
    async with AsyncGraphDatabase.driver(uri, auth=("neo4j", "test-password")) as driver:
        repository = Neo4jProgramRepository(driver)
        await repository.ensure_schema()
        await repository.seed_demo_program()
        profile = BusinessProfile.model_validate(
            {"business_type": "CORPORATION", "hq_region": "대전", "query_date": "2026-10-07"}
        )
        programs = await repository.find_candidates(profile)
        assert programs[0].program_id == "PBLN_DEMO"
        assert len(programs[0].conditions) == 7
        evidence = await repository.find_evidence([r.evidence_id for r in programs[0].conditions])
        assert len(evidence) == 7
        assert all(item.source_kind == "SYNTHETIC_DEMO" for item in evidence)
