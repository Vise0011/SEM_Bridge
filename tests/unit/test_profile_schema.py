"""Tests for the business profile input contract."""

from datetime import date

import pytest
from pydantic import ValidationError

from sme_bridge.schemas import BusinessProfile


def valid_profile_data() -> dict[str, object]:
    return {
        "business_type": "CORPORATION",
        "established_date": date(2023, 3, 15),
        "hq_region": "대전",
        "industry_code": "J62",
        "employee_count": 8,
        "annual_sales_band": "UNDER_1B_KRW",
        "certifications": [],
        "funding_purpose": "WORKING_CAPITAL",
        "query_date": date(2026, 9, 12),
    }


def test_accepts_valid_business_profile() -> None:
    profile = BusinessProfile.model_validate(valid_profile_data())

    assert profile.hq_region == "대전"
    assert profile.employee_count == 8


def test_rejects_negative_employee_count() -> None:
    data = valid_profile_data()
    data["employee_count"] = -1

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        BusinessProfile.model_validate(data)


def test_rejects_establishment_after_query_date() -> None:
    data = valid_profile_data()
    data["established_date"] = date(2027, 1, 1)

    with pytest.raises(ValidationError, match="cannot be later than query_date"):
        BusinessProfile.model_validate(data)


def test_accepts_missing_establishment_date_for_unknown_decision() -> None:
    data = valid_profile_data()
    del data["established_date"]

    profile = BusinessProfile.model_validate(data)

    assert profile.established_date is None
