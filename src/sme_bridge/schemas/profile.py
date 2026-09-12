"""Business profile schema used as eligibility-check input."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BusinessType(StrEnum):
    """Supported legal forms for a business."""

    CORPORATION = "CORPORATION"
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR"


class AnnualSalesBand(StrEnum):
    """Coarse annual-sales bands used by the prototype."""

    UNDER_1B_KRW = "UNDER_1B_KRW"
    FROM_1B_TO_5B_KRW = "FROM_1B_TO_5B_KRW"
    OVER_5B_KRW = "OVER_5B_KRW"


class FundingPurpose(StrEnum):
    """Purposes supported by the prototype."""

    WORKING_CAPITAL = "WORKING_CAPITAL"
    FACILITY_CAPITAL = "FACILITY_CAPITAL"
    BOTH = "BOTH"


class BusinessProfile(BaseModel):
    """Validated synthetic company profile supplied to the API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    business_type: BusinessType
    established_date: date | None = None
    hq_region: str | None = Field(default=None, min_length=1, max_length=30)
    industry_code: str | None = Field(default=None, pattern=r"^[A-Z][0-9]{2}$")
    employee_count: int | None = Field(default=None, ge=0)
    annual_sales_band: AnnualSalesBand | None = None
    certifications: list[str] | None = None
    funding_purpose: FundingPurpose | None = None
    query_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> "BusinessProfile":
        if self.established_date is not None and self.established_date > self.query_date:
            raise ValueError("established_date cannot be later than query_date")
        return self
