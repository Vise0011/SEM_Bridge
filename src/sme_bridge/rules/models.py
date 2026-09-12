"""Schemas shared by deterministic eligibility rules."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleStatus(StrEnum):
    """A rule result never guesses when information is missing."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ReasonCode(StrEnum):
    """Machine-readable reasons for rule outcomes."""

    MATCH = "MATCH"
    MISSING_VALUE = "MISSING_VALUE"
    REGION_NOT_ALLOWED = "REGION_NOT_ALLOWED"
    BELOW_MINIMUM = "BELOW_MINIMUM"
    ABOVE_MAXIMUM = "ABOVE_MAXIMUM"
    WITHIN_RANGE = "WITHIN_RANGE"
    BUSINESS_TOO_NEW = "BUSINESS_TOO_NEW"
    BUSINESS_TOO_OLD = "BUSINESS_TOO_OLD"
    APPLICATION_NOT_OPEN = "APPLICATION_NOT_OPEN"
    APPLICATION_CLOSED = "APPLICATION_CLOSED"
    DATE_IN_WINDOW = "DATE_IN_WINDOW"
    INDUSTRY_NOT_ALLOWED = "INDUSTRY_NOT_ALLOWED"
    SALES_BAND_NOT_ALLOWED = "SALES_BAND_NOT_ALLOWED"
    FUNDING_PURPOSE_NOT_ALLOWED = "FUNDING_PURPOSE_NOT_ALLOWED"
    CERTIFICATION_MISSING = "CERTIFICATION_MISSING"


class RegionRule(BaseModel):
    """Approved region condition extracted from a notice."""

    model_config = ConfigDict(frozen=True)

    field: Literal["hq_region"] = "hq_region"
    allowed_regions: frozenset[str] = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class EmployeeCountRule(BaseModel):
    """Approved inclusive employee-count condition."""

    model_config = ConfigDict(frozen=True)

    field: Literal["employee_count"] = "employee_count"
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> "EmployeeCountRule":
        if self.minimum is None and self.maximum is None:
            raise ValueError("at least one employee-count boundary is required")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class BusinessAgeRule(BaseModel):
    """Approved inclusive business-age condition measured in full years."""

    model_config = ConfigDict(frozen=True)

    field: Literal["business_age_years"] = "business_age_years"
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> "BusinessAgeRule":
        if self.minimum is None and self.maximum is None:
            raise ValueError("at least one business-age boundary is required")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class ApplicationPeriodRule(BaseModel):
    """Approved inclusive application window."""

    model_config = ConfigDict(frozen=True)

    field: Literal["query_date"] = "query_date"
    starts_on: date
    ends_on: date
    evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_period(self) -> "ApplicationPeriodRule":
        if self.starts_on > self.ends_on:
            raise ValueError("starts_on cannot be later than ends_on")
        return self


class IndustryRule(BaseModel):
    """Approved industry-code allowlist."""

    model_config = ConfigDict(frozen=True)

    field: Literal["industry_code"] = "industry_code"
    allowed_codes: frozenset[str] = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class AnnualSalesRule(BaseModel):
    """Approved annual-sales-band allowlist."""

    model_config = ConfigDict(frozen=True)

    field: Literal["annual_sales_band"] = "annual_sales_band"
    allowed_bands: frozenset[str] = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class FundingPurposeRule(BaseModel):
    """Approved funding-purpose allowlist."""

    model_config = ConfigDict(frozen=True)

    field: Literal["funding_purpose"] = "funding_purpose"
    allowed_purposes: frozenset[str] = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class CertificationRule(BaseModel):
    """Condition requiring at least one certification from an approved set."""

    model_config = ConfigDict(frozen=True)

    field: Literal["certifications"] = "certifications"
    required_any_of: frozenset[str] = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


ApprovedRule = Annotated[
    RegionRule
    | EmployeeCountRule
    | BusinessAgeRule
    | ApplicationPeriodRule
    | IndustryRule
    | AnnualSalesRule
    | FundingPurposeRule
    | CertificationRule,
    Field(discriminator="field"),
]


class RuleResult(BaseModel):
    """Serializable result of one deterministic rule evaluation."""

    field: str
    status: RuleStatus
    reason_code: ReasonCode
    observed: str | int | list[str] | None
    expected: list[str] | dict[str, str | int | None]
    evidence_id: str
