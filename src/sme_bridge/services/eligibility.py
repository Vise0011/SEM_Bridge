"""Eligibility evaluation services used by the API."""

from collections.abc import Sequence

from sme_bridge.rules import (
    AnnualSalesRule,
    ApplicationPeriodRule,
    BusinessAgeRule,
    CertificationRule,
    EmployeeCountRule,
    FundingPurposeRule,
    IndustryRule,
    RegionRule,
    RuleResult,
    RuleStatus,
    evaluate_annual_sales,
    evaluate_application_period,
    evaluate_business_age,
    evaluate_certifications,
    evaluate_employee_count,
    evaluate_funding_purpose,
    evaluate_industry,
    evaluate_region,
)
from sme_bridge.schemas.case import ProgramEvaluation
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition

FOLLOW_UP_QUESTIONS = {
    "hq_region": "기업의 본사 소재 지역을 알려주세요.",
    "employee_count": "현재 상시 종업원 수를 알려주세요.",
    "business_age_years": "기업의 설립일을 알려주세요.",
    "industry_code": "기업의 업종 코드를 알려주세요.",
    "annual_sales_band": "기업의 연간 매출 구간을 알려주세요.",
    "funding_purpose": "자금의 사용 목적을 알려주세요.",
    "certifications": "보유한 기업 인증을 알려주세요. 없다면 빈 목록으로 제출하세요.",
}


def aggregate_status(results: Sequence[RuleResult]) -> RuleStatus:
    """Aggregate rule outcomes conservatively: FAIL, then UNKNOWN, then PASS."""
    statuses = {result.status for result in results}
    if RuleStatus.FAIL in statuses:
        return RuleStatus.FAIL
    if RuleStatus.UNKNOWN in statuses:
        return RuleStatus.UNKNOWN
    return RuleStatus.PASS


def evaluate_program(
    profile: BusinessProfile,
    program: ProgramDefinition,
) -> ProgramEvaluation:
    """Evaluate one profile using only a program's approved typed rules."""
    results: list[RuleResult] = []
    for rule in program.conditions:
        if isinstance(rule, EmployeeCountRule):
            results.append(evaluate_employee_count(profile.employee_count, rule))
        elif isinstance(rule, RegionRule):
            results.append(evaluate_region(profile.hq_region, rule))
        elif isinstance(rule, BusinessAgeRule):
            results.append(
                evaluate_business_age(profile.established_date, profile.query_date, rule)
            )
        elif isinstance(rule, ApplicationPeriodRule):
            results.append(evaluate_application_period(profile.query_date, rule))
        elif isinstance(rule, IndustryRule):
            results.append(evaluate_industry(profile.industry_code, rule))
        elif isinstance(rule, AnnualSalesRule):
            observed = (
                None if profile.annual_sales_band is None else profile.annual_sales_band.value
            )
            results.append(evaluate_annual_sales(observed, rule))
        elif isinstance(rule, FundingPurposeRule):
            observed = None if profile.funding_purpose is None else profile.funding_purpose.value
            results.append(evaluate_funding_purpose(observed, rule))
        elif isinstance(rule, CertificationRule):
            results.append(evaluate_certifications(profile.certifications, rule))

    missing_fields = list(
        dict.fromkeys(result.field for result in results if result.status is RuleStatus.UNKNOWN)
    )
    follow_up_questions = [
        FOLLOW_UP_QUESTIONS[field] for field in missing_fields if field in FOLLOW_UP_QUESTIONS
    ]

    return ProgramEvaluation(
        program_id=program.program_id,
        status=aggregate_status(results),
        rule_results=results,
        missing_fields=missing_fields,
        follow_up_questions=follow_up_questions,
        review_required=bool(missing_fields),
    )


def attach_verified_evidence(
    evaluation: ProgramEvaluation,
    available: list[EvidenceReference],
) -> ProgramEvaluation:
    """Attach citations and downgrade any result whose approved evidence is missing."""
    by_id = {item.evidence_id: item for item in available}
    required_ids = list(dict.fromkeys(result.evidence_id for result in evaluation.rule_results))
    evidence = [by_id[evidence_id] for evidence_id in required_ids if evidence_id in by_id]
    missing = [evidence_id for evidence_id in required_ids if evidence_id not in by_id]

    updates: dict[str, object] = {
        "evidence": evidence,
        "missing_evidence_ids": missing,
    }
    if missing:
        updates["status"] = RuleStatus.UNKNOWN
        updates["review_required"] = True
    return evaluation.model_copy(update=updates)
