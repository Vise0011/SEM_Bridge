"""Boundary tests for deterministic eligibility rules."""

import pytest
from pydantic import ValidationError

from sme_bridge.rules import (
    EmployeeCountRule,
    ReasonCode,
    RegionRule,
    RuleStatus,
    evaluate_employee_count,
    evaluate_region,
)


def test_region_passes_when_value_is_allowed() -> None:
    rule = RegionRule(allowed_regions={"대전", "세종"}, evidence_id="EV-REGION-1")

    result = evaluate_region("대전", rule)

    assert result.status is RuleStatus.PASS
    assert result.reason_code is ReasonCode.MATCH


def test_region_fails_when_value_is_not_allowed() -> None:
    rule = RegionRule(allowed_regions={"대전"}, evidence_id="EV-REGION-1")

    result = evaluate_region("서울", rule)

    assert result.status is RuleStatus.FAIL
    assert result.reason_code is ReasonCode.REGION_NOT_ALLOWED


def test_region_is_unknown_when_value_is_missing() -> None:
    rule = RegionRule(allowed_regions={"대전"}, evidence_id="EV-REGION-1")

    result = evaluate_region(None, rule)

    assert result.status is RuleStatus.UNKNOWN
    assert result.reason_code is ReasonCode.MISSING_VALUE


@pytest.mark.parametrize("boundary", [5, 10])
def test_employee_count_passes_on_inclusive_boundaries(boundary: int) -> None:
    rule = EmployeeCountRule(minimum=5, maximum=10, evidence_id="EV-EMPLOYEE-1")

    result = evaluate_employee_count(boundary, rule)

    assert result.status is RuleStatus.PASS
    assert result.reason_code is ReasonCode.WITHIN_RANGE


@pytest.mark.parametrize(
    ("observed", "reason_code"),
    [(4, ReasonCode.BELOW_MINIMUM), (11, ReasonCode.ABOVE_MAXIMUM)],
)
def test_employee_count_fails_outside_range(observed: int, reason_code: ReasonCode) -> None:
    rule = EmployeeCountRule(minimum=5, maximum=10, evidence_id="EV-EMPLOYEE-1")

    result = evaluate_employee_count(observed, rule)

    assert result.status is RuleStatus.FAIL
    assert result.reason_code is reason_code


def test_employee_count_is_unknown_when_value_is_missing() -> None:
    rule = EmployeeCountRule(maximum=10, evidence_id="EV-EMPLOYEE-1")

    result = evaluate_employee_count(None, rule)

    assert result.status is RuleStatus.UNKNOWN
    assert result.reason_code is ReasonCode.MISSING_VALUE


def test_employee_count_rule_rejects_invalid_range() -> None:
    with pytest.raises(ValidationError, match="minimum cannot exceed maximum"):
        EmployeeCountRule(minimum=10, maximum=5, evidence_id="EV-EMPLOYEE-1")
