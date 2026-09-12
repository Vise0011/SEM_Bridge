"""Case intake routes."""

from datetime import date
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sme_bridge.repositories import (
    CaseRepository,
    InMemoryCaseRepository,
    InMemoryProgramRepository,
    ProgramRepository,
)
from sme_bridge.rules import (
    AnnualSalesRule,
    ApplicationPeriodRule,
    BusinessAgeRule,
    EmployeeCountRule,
    FundingPurposeRule,
    IndustryRule,
    RegionRule,
)
from sme_bridge.schemas.case import CaseCreated, CaseStatus
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.services.eligibility import attach_verified_evidence, evaluate_program

router = APIRouter(prefix="/v1/cases", tags=["cases"])
_unit_test_repository = InMemoryCaseRepository()
_unit_test_program_repository = InMemoryProgramRepository(
    [
        ProgramDefinition(
            program_id="PBLN_DEMO",
            title="대전 소기업 운전자금 데모",
            conditions=[
                RegionRule(
                    allowed_regions=frozenset({"대전"}),
                    evidence_id="EV-DEMO-REGION",
                ),
                EmployeeCountRule(
                    maximum=10,
                    evidence_id="EV-DEMO-EMPLOYEE",
                ),
                BusinessAgeRule(
                    minimum=0,
                    maximum=7,
                    evidence_id="EV-DEMO-AGE",
                ),
                ApplicationPeriodRule(
                    starts_on=date(2026, 1, 1),
                    ends_on=date(2026, 12, 31),
                    evidence_id="EV-DEMO-PERIOD",
                ),
                IndustryRule(
                    allowed_codes=frozenset({"J62"}),
                    evidence_id="EV-DEMO-INDUSTRY",
                ),
                AnnualSalesRule(
                    allowed_bands=frozenset({"UNDER_1B_KRW"}),
                    evidence_id="EV-DEMO-SALES",
                ),
                FundingPurposeRule(
                    allowed_purposes=frozenset({"WORKING_CAPITAL", "BOTH"}),
                    evidence_id="EV-DEMO-FUNDING",
                ),
            ],
        )
    ]
)


def get_case_repository(request: Request) -> CaseRepository:
    """Resolve the repository installed during application startup."""
    repository = getattr(request.app.state, "case_repository", _unit_test_repository)
    return cast(CaseRepository, repository)


def get_program_repository(request: Request) -> ProgramRepository:
    """Resolve the approved-program repository installed at startup."""
    repository = getattr(
        request.app.state,
        "program_repository",
        _unit_test_program_repository,
    )
    return cast(ProgramRepository, repository)


@router.post("", response_model=CaseCreated, status_code=status.HTTP_201_CREATED)
async def create_case(
    profile: BusinessProfile,
    repository: Annotated[CaseRepository, Depends(get_case_repository)],
    program_repository: Annotated[ProgramRepository, Depends(get_program_repository)],
) -> CaseCreated:
    """Validate and accept a synthetic business profile for later evaluation."""
    definitions = await program_repository.find_candidates(profile, limit=3)
    evaluations = [evaluate_program(profile, definition) for definition in definitions]
    evidence_ids = list(
        dict.fromkeys(
            result.evidence_id for evaluation in evaluations for result in evaluation.rule_results
        )
    )
    available_evidence = await program_repository.find_evidence(evidence_ids)
    case = CaseCreated(
        case_id=f"case_{uuid4().hex}",
        status=CaseStatus.RULE_CHECKED,
        profile=profile,
        programs=[
            attach_verified_evidence(evaluation, available_evidence) for evaluation in evaluations
        ],
    )
    await repository.save(case)
    return case


@router.get("/{case_id}", response_model=CaseCreated)
async def get_case(
    case_id: str,
    repository: Annotated[CaseRepository, Depends(get_case_repository)],
) -> CaseCreated:
    """Return the immutable snapshot stored for a case."""
    case = await repository.find(case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )
    return case
