"""Boundary tests for business-age and application-period rules."""

from datetime import date

import pytest
from pydantic import ValidationError

from sme_bridge.rules import (
    ApplicationPeriodRule,
    BusinessAgeRule,
    ReasonCode,
    RuleStatus,
    evaluate_application_period,
    evaluate_business_age,
    full_years_between,
)


def test_full_years_waits_for_anniversary() -> None:
    established = date(2023, 9, 13)

    assert full_years_between(established, date(2026, 9, 12)) == 2
    assert full_years_between(established, date(2026, 9, 13)) == 3


def test_business_age_is_unknown_without_establishment_date() -> None:
    rule = BusinessAgeRule(minimum=3, evidence_id="EV-AGE")

    result = evaluate_business_age(None, date(2026, 9, 12), rule)

    assert result.status is RuleStatus.UNKNOWN
    assert result.reason_code is ReasonCode.MISSING_VALUE


@pytest.mark.parametrize(
    ("established", "reason"),
    [
        (date(2025, 1, 1), ReasonCode.BUSINESS_TOO_NEW),
        (date(2010, 1, 1), ReasonCode.BUSINESS_TOO_OLD),
    ],
)
def test_business_age_fails_outside_range(established: date, reason: ReasonCode) -> None:
    rule = BusinessAgeRule(minimum=3, maximum=7, evidence_id="EV-AGE")

    result = evaluate_business_age(established, date(2026, 9, 12), rule)

    assert result.status is RuleStatus.FAIL
    assert result.reason_code is reason


@pytest.mark.parametrize("observed", [date(2026, 1, 1), date(2026, 12, 31)])
def test_application_period_includes_both_boundaries(observed: date) -> None:
    rule = ApplicationPeriodRule(
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 31),
        evidence_id="EV-PERIOD",
    )

    result = evaluate_application_period(observed, rule)

    assert result.status is RuleStatus.PASS
    assert result.reason_code is ReasonCode.DATE_IN_WINDOW


@pytest.mark.parametrize(
    ("observed", "reason"),
    [
        (date(2025, 12, 31), ReasonCode.APPLICATION_NOT_OPEN),
        (date(2027, 1, 1), ReasonCode.APPLICATION_CLOSED),
    ],
)
def test_application_period_fails_outside_window(observed: date, reason: ReasonCode) -> None:
    rule = ApplicationPeriodRule(
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 31),
        evidence_id="EV-PERIOD",
    )

    result = evaluate_application_period(observed, rule)

    assert result.status is RuleStatus.FAIL
    assert result.reason_code is reason


def test_application_period_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="starts_on cannot be later than ends_on"):
        ApplicationPeriodRule(
            starts_on=date(2026, 12, 31),
            ends_on=date(2026, 1, 1),
            evidence_id="EV-PERIOD",
        )
