"""Tests for conservative result aggregation."""

from sme_bridge.rules import EmployeeCountRule, ReasonCode, RegionRule, RuleResult, RuleStatus
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.services.eligibility import (
    aggregate_status,
    attach_verified_evidence,
    evaluate_program,
)


def result(status: RuleStatus) -> RuleResult:
    return RuleResult(
        field="test_field",
        status=status,
        reason_code=ReasonCode.MATCH,
        observed="value",
        expected=["value"],
        evidence_id="EV-TEST",
    )


def test_aggregate_status_prioritizes_fail() -> None:
    results = [result(RuleStatus.UNKNOWN), result(RuleStatus.FAIL)]

    assert aggregate_status(results) is RuleStatus.FAIL


def test_aggregate_status_returns_unknown_without_failure() -> None:
    results = [result(RuleStatus.PASS), result(RuleStatus.UNKNOWN)]

    assert aggregate_status(results) is RuleStatus.UNKNOWN


def test_aggregate_status_returns_pass_when_all_rules_pass() -> None:
    results = [result(RuleStatus.PASS), result(RuleStatus.PASS)]

    assert aggregate_status(results) is RuleStatus.PASS


def test_empty_results_never_pass() -> None:
    assert aggregate_status([]) is RuleStatus.UNKNOWN


def test_mismatched_official_notice_evidence_never_verifies() -> None:
    profile = BusinessProfile.model_validate(
        {
            "business_type": "CORPORATION",
            "hq_region": "대전",
            "query_date": "2026-10-07",
        }
    )
    program = ProgramDefinition(
        program_id="PBLN_TEST",
        title="공식 테스트",
        source_kind="OFFICIAL_NOTICE",
        notice_version="sha256:version-a",
        conditions=[RegionRule(allowed_regions=frozenset({"대전"}), evidence_id="EV-1")],
    )
    evidence = EvidenceReference(
        evidence_id="EV-1",
        passage="대전 소재 기업",
        notice_version="sha256:version-b",
        source_kind="OFFICIAL_NOTICE",
        pdf_sha256="a" * 64,
    )
    result = attach_verified_evidence(evaluate_program(profile, program), [evidence])
    assert result.status is RuleStatus.UNKNOWN
    assert result.missing_evidence_ids == ["EV-1"]


def test_evaluate_program_uses_typed_approved_conditions() -> None:
    profile = BusinessProfile.model_validate(
        {
            "business_type": "CORPORATION",
            "established_date": "2023-03-15",
            "hq_region": "대전",
            "industry_code": "J62",
            "employee_count": 8,
            "annual_sales_band": "UNDER_1B_KRW",
            "funding_purpose": "WORKING_CAPITAL",
            "query_date": "2026-09-12",
        }
    )
    program = ProgramDefinition(
        program_id="PBLN_TEST",
        title="테스트 사업",
        conditions=[
            RegionRule(allowed_regions=frozenset({"대전"}), evidence_id="EV-1"),
            EmployeeCountRule(maximum=10, evidence_id="EV-2"),
        ],
    )

    evaluation = evaluate_program(profile, program)

    assert evaluation.program_id == "PBLN_TEST"
    assert evaluation.status is RuleStatus.PASS
    assert [result.evidence_id for result in evaluation.rule_results] == ["EV-1", "EV-2"]


def test_evaluate_program_builds_questions_for_missing_values() -> None:
    profile = BusinessProfile.model_validate(
        {
            "business_type": "CORPORATION",
            "query_date": "2026-09-12",
        }
    )
    program = ProgramDefinition(
        program_id="PBLN_TEST",
        title="테스트 사업",
        conditions=[
            RegionRule(allowed_regions=frozenset({"대전"}), evidence_id="EV-1"),
            EmployeeCountRule(maximum=10, evidence_id="EV-2"),
        ],
    )

    evaluation = evaluate_program(profile, program)

    assert evaluation.status is RuleStatus.UNKNOWN
    assert evaluation.missing_fields == ["hq_region", "employee_count"]
    assert evaluation.review_required is True
    assert len(evaluation.follow_up_questions) == 2


def test_missing_evidence_downgrades_pass_to_unknown() -> None:
    profile = BusinessProfile.model_validate(
        {"business_type": "CORPORATION", "hq_region": "대전", "query_date": "2026-09-12"}
    )
    program = ProgramDefinition(
        program_id="PBLN_TEST",
        title="테스트 사업",
        conditions=[RegionRule(allowed_regions=frozenset({"대전"}), evidence_id="EV-MISSING")],
    )
    evaluation = evaluate_program(profile, program)

    verified = attach_verified_evidence(evaluation, [])

    assert verified.status is RuleStatus.UNKNOWN
    assert verified.review_required is True
    assert verified.missing_evidence_ids == ["EV-MISSING"]


def test_complete_evidence_preserves_pass() -> None:
    profile = BusinessProfile.model_validate(
        {"business_type": "CORPORATION", "hq_region": "대전", "query_date": "2026-09-12"}
    )
    program = ProgramDefinition(
        program_id="PBLN_TEST",
        title="테스트 사업",
        conditions=[RegionRule(allowed_regions=frozenset({"대전"}), evidence_id="EV-1")],
    )
    evaluation = evaluate_program(profile, program)
    evidence = EvidenceReference(
        evidence_id="EV-1",
        passage="대전 소재 기업",
        page=1,
        notice_version="sha256:test",
        source_kind="SYNTHETIC_DEMO",
    )

    verified = attach_verified_evidence(evaluation, [evidence])

    assert verified.status is RuleStatus.PASS
    assert verified.evidence == [evidence]
    assert verified.missing_evidence_ids == []
