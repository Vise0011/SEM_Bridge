"""Tests for allowlist and certification rules."""

import pytest

from sme_bridge.rules import (
    AnnualSalesRule,
    CertificationRule,
    FundingPurposeRule,
    IndustryRule,
    ReasonCode,
    RuleStatus,
    evaluate_annual_sales,
    evaluate_certifications,
    evaluate_funding_purpose,
    evaluate_industry,
)


@pytest.mark.parametrize(
    ("observed", "status", "reason"),
    [
        ("J62", RuleStatus.PASS, ReasonCode.MATCH),
        ("C10", RuleStatus.FAIL, ReasonCode.INDUSTRY_NOT_ALLOWED),
        (None, RuleStatus.UNKNOWN, ReasonCode.MISSING_VALUE),
    ],
)
def test_industry_allowlist(
    observed: str | None,
    status: RuleStatus,
    reason: ReasonCode,
) -> None:
    rule = IndustryRule(allowed_codes=frozenset({"J62"}), evidence_id="EV-INDUSTRY")

    result = evaluate_industry(observed, rule)

    assert result.status is status
    assert result.reason_code is reason


def test_annual_sales_and_funding_purpose_allowlists() -> None:
    sales = evaluate_annual_sales(
        "UNDER_1B_KRW",
        AnnualSalesRule(
            allowed_bands=frozenset({"UNDER_1B_KRW"}),
            evidence_id="EV-SALES",
        ),
    )
    funding = evaluate_funding_purpose(
        "FACILITY_CAPITAL",
        FundingPurposeRule(
            allowed_purposes=frozenset({"WORKING_CAPITAL"}),
            evidence_id="EV-FUNDING",
        ),
    )

    assert sales.status is RuleStatus.PASS
    assert funding.status is RuleStatus.FAIL
    assert funding.reason_code is ReasonCode.FUNDING_PURPOSE_NOT_ALLOWED


def test_missing_certifications_are_unknown_but_known_empty_is_fail() -> None:
    rule = CertificationRule(
        required_any_of=frozenset({"벤처기업", "이노비즈"}),
        evidence_id="EV-CERT",
    )

    missing = evaluate_certifications(None, rule)
    known_empty = evaluate_certifications([], rule)
    matching = evaluate_certifications(["벤처기업"], rule)

    assert missing.status is RuleStatus.UNKNOWN
    assert known_empty.status is RuleStatus.FAIL
    assert known_empty.reason_code is ReasonCode.CERTIFICATION_MISSING
    assert matching.status is RuleStatus.PASS
