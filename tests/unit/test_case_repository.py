"""Tests for the repository contract's in-memory implementation."""

from datetime import date

import pytest

from sme_bridge.repositories import InMemoryCaseRepository
from sme_bridge.schemas.case import CaseCreated, CaseStatus
from sme_bridge.schemas.profile import BusinessProfile


@pytest.mark.asyncio
async def test_in_memory_repository_saves_case() -> None:
    profile = BusinessProfile(
        business_type="CORPORATION",
        established_date=date(2023, 3, 15),
        hq_region="대전",
        industry_code="J62",
        employee_count=8,
        annual_sales_band="UNDER_1B_KRW",
        funding_purpose="WORKING_CAPITAL",
        query_date=date(2026, 9, 12),
    )
    case = CaseCreated(
        case_id="case_test",
        status=CaseStatus.RULE_CHECKED,
        profile=profile,
        programs=[],
    )
    repository = InMemoryCaseRepository()

    await repository.save(case)

    assert repository.items["case_test"] == case
    assert await repository.find("case_test") == case
    assert await repository.find("case_missing") is None
