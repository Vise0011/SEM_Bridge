"""Pure functions for deterministic eligibility decisions."""

from datetime import date

from sme_bridge.rules.models import (
    AnnualSalesRule,
    ApplicationPeriodRule,
    BusinessAgeRule,
    CertificationRule,
    EmployeeCountRule,
    FundingPurposeRule,
    IndustryRule,
    ReasonCode,
    RegionRule,
    RuleResult,
    RuleStatus,
)


def full_years_between(established_date: date, query_date: date) -> int:
    """Return completed calendar years, accounting for the anniversary date."""
    anniversary_not_reached = (query_date.month, query_date.day) < (
        established_date.month,
        established_date.day,
    )
    return query_date.year - established_date.year - int(anniversary_not_reached)


def evaluate_region(observed: str | None, rule: RegionRule) -> RuleResult:
    """Evaluate a headquarters region against an approved allowlist."""
    expected = sorted(rule.allowed_regions)

    if observed is None:
        return RuleResult(
            field=rule.field,
            status=RuleStatus.UNKNOWN,
            reason_code=ReasonCode.MISSING_VALUE,
            observed=None,
            expected=expected,
            evidence_id=rule.evidence_id,
        )

    if observed in rule.allowed_regions:
        status = RuleStatus.PASS
        reason_code = ReasonCode.MATCH
    else:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.REGION_NOT_ALLOWED

    return RuleResult(
        field=rule.field,
        status=status,
        reason_code=reason_code,
        observed=observed,
        expected=expected,
        evidence_id=rule.evidence_id,
    )


def evaluate_employee_count(observed: int | None, rule: EmployeeCountRule) -> RuleResult:
    """Evaluate an employee count using inclusive approved boundaries."""
    expected: dict[str, str | int | None] = {
        "minimum": rule.minimum,
        "maximum": rule.maximum,
    }

    if observed is None:
        return RuleResult(
            field=rule.field,
            status=RuleStatus.UNKNOWN,
            reason_code=ReasonCode.MISSING_VALUE,
            observed=None,
            expected=expected,
            evidence_id=rule.evidence_id,
        )

    if rule.minimum is not None and observed < rule.minimum:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.BELOW_MINIMUM
    elif rule.maximum is not None and observed > rule.maximum:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.ABOVE_MAXIMUM
    else:
        status = RuleStatus.PASS
        reason_code = ReasonCode.WITHIN_RANGE

    return RuleResult(
        field=rule.field,
        status=status,
        reason_code=reason_code,
        observed=observed,
        expected=expected,
        evidence_id=rule.evidence_id,
    )


def evaluate_business_age(
    established_date: date | None,
    query_date: date,
    rule: BusinessAgeRule,
) -> RuleResult:
    """Evaluate completed business years using inclusive boundaries."""
    expected: dict[str, str | int | None] = {
        "minimum": rule.minimum,
        "maximum": rule.maximum,
    }
    if established_date is None:
        return RuleResult(
            field=rule.field,
            status=RuleStatus.UNKNOWN,
            reason_code=ReasonCode.MISSING_VALUE,
            observed=None,
            expected=expected,
            evidence_id=rule.evidence_id,
        )

    observed = full_years_between(established_date, query_date)
    if rule.minimum is not None and observed < rule.minimum:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.BUSINESS_TOO_NEW
    elif rule.maximum is not None and observed > rule.maximum:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.BUSINESS_TOO_OLD
    else:
        status = RuleStatus.PASS
        reason_code = ReasonCode.WITHIN_RANGE

    return RuleResult(
        field=rule.field,
        status=status,
        reason_code=reason_code,
        observed=observed,
        expected=expected,
        evidence_id=rule.evidence_id,
    )


def evaluate_application_period(
    observed: date,
    rule: ApplicationPeriodRule,
) -> RuleResult:
    """Evaluate a query date against an inclusive application window."""
    expected: dict[str, str | int | None] = {
        "starts_on": rule.starts_on.isoformat(),
        "ends_on": rule.ends_on.isoformat(),
    }
    if observed < rule.starts_on:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.APPLICATION_NOT_OPEN
    elif observed > rule.ends_on:
        status = RuleStatus.FAIL
        reason_code = ReasonCode.APPLICATION_CLOSED
    else:
        status = RuleStatus.PASS
        reason_code = ReasonCode.DATE_IN_WINDOW

    return RuleResult(
        field=rule.field,
        status=status,
        reason_code=reason_code,
        observed=observed.isoformat(),
        expected=expected,
        evidence_id=rule.evidence_id,
    )


def _evaluate_allowlist(
    *,
    field: str,
    observed: str | None,
    allowed: frozenset[str],
    evidence_id: str,
    fail_reason: ReasonCode,
) -> RuleResult:
    expected = sorted(allowed)
    if observed is None:
        return RuleResult(
            field=field,
            status=RuleStatus.UNKNOWN,
            reason_code=ReasonCode.MISSING_VALUE,
            observed=None,
            expected=expected,
            evidence_id=evidence_id,
        )
    return RuleResult(
        field=field,
        status=RuleStatus.PASS if observed in allowed else RuleStatus.FAIL,
        reason_code=ReasonCode.MATCH if observed in allowed else fail_reason,
        observed=observed,
        expected=expected,
        evidence_id=evidence_id,
    )


def evaluate_industry(observed: str | None, rule: IndustryRule) -> RuleResult:
    return _evaluate_allowlist(
        field=rule.field,
        observed=observed,
        allowed=rule.allowed_codes,
        evidence_id=rule.evidence_id,
        fail_reason=ReasonCode.INDUSTRY_NOT_ALLOWED,
    )


def evaluate_annual_sales(observed: str | None, rule: AnnualSalesRule) -> RuleResult:
    return _evaluate_allowlist(
        field=rule.field,
        observed=observed,
        allowed=rule.allowed_bands,
        evidence_id=rule.evidence_id,
        fail_reason=ReasonCode.SALES_BAND_NOT_ALLOWED,
    )


def evaluate_funding_purpose(
    observed: str | None,
    rule: FundingPurposeRule,
) -> RuleResult:
    return _evaluate_allowlist(
        field=rule.field,
        observed=observed,
        allowed=rule.allowed_purposes,
        evidence_id=rule.evidence_id,
        fail_reason=ReasonCode.FUNDING_PURPOSE_NOT_ALLOWED,
    )


def evaluate_certifications(
    observed: list[str] | None,
    rule: CertificationRule,
) -> RuleResult:
    expected = sorted(rule.required_any_of)
    if observed is None:
        return RuleResult(
            field=rule.field,
            status=RuleStatus.UNKNOWN,
            reason_code=ReasonCode.MISSING_VALUE,
            observed=None,
            expected=expected,
            evidence_id=rule.evidence_id,
        )
    matched = bool(set(observed) & rule.required_any_of)
    return RuleResult(
        field=rule.field,
        status=RuleStatus.PASS if matched else RuleStatus.FAIL,
        reason_code=ReasonCode.MATCH if matched else ReasonCode.CERTIFICATION_MISSING,
        observed=observed,
        expected=expected,
        evidence_id=rule.evidence_id,
    )
