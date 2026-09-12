"""Tests for deterministic candidate ranking."""

from datetime import date

import pytest

from sme_bridge.repositories import InMemoryProgramRepository
from sme_bridge.rules import EmployeeCountRule, RegionRule
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition


def profile(region: str | None = "대전", employees: int | None = 8) -> BusinessProfile:
    return BusinessProfile(
        business_type="CORPORATION",
        established_date=date(2023, 3, 15),
        hq_region=region,
        industry_code="J62",
        employee_count=employees,
        annual_sales_band="UNDER_1B_KRW",
        funding_purpose="WORKING_CAPITAL",
        query_date=date(2026, 9, 12),
    )


def program(program_id: str, region: str, maximum: int) -> ProgramDefinition:
    return ProgramDefinition(
        program_id=program_id,
        title=f"{program_id} 사업",
        conditions=[
            RegionRule(
                allowed_regions=frozenset({region}),
                evidence_id=f"EV-{program_id}-REGION",
            ),
            EmployeeCountRule(
                maximum=maximum,
                evidence_id=f"EV-{program_id}-EMPLOYEE",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_candidates_are_ranked_by_matching_conditions() -> None:
    repository = InMemoryProgramRepository(
        [
            program("P3", "서울", 5),
            program("P2", "대전", 5),
            program("P1", "대전", 10),
        ]
    )

    candidates = await repository.find_candidates(profile(), limit=3)

    assert [candidate.program_id for candidate in candidates] == ["P1", "P2", "P3"]


@pytest.mark.asyncio
async def test_candidates_are_limited_to_top_three() -> None:
    repository = InMemoryProgramRepository([program(f"P{index}", "대전", 10) for index in range(5)])

    candidates = await repository.find_candidates(profile(), limit=3)

    assert len(candidates) == 3
    assert [candidate.program_id for candidate in candidates] == ["P0", "P1", "P2"]


@pytest.mark.asyncio
async def test_missing_profile_values_do_not_remove_candidates() -> None:
    repository = InMemoryProgramRepository([program("P2", "서울", 5), program("P1", "대전", 10)])

    candidates = await repository.find_candidates(profile(region=None, employees=None))

    assert [candidate.program_id for candidate in candidates] == ["P1", "P2"]
