"""Case intake routes."""

import hashlib
import json
from datetime import date
from typing import Annotated, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from sme_bridge.api.routes.notices import get_notice_repository
from sme_bridge.repositories import (
    CaseRepository,
    InMemoryProgramRepository,
    NoticeRepository,
    ProgramRepository,
)
from sme_bridge.repositories.cases import IdempotencyConflict
from sme_bridge.rules import (
    AnnualSalesRule,
    ApplicationPeriodRule,
    BusinessAgeRule,
    EmployeeCountRule,
    FundingPurposeRule,
    IndustryRule,
    RegionRule,
    RuleStatus,
)
from sme_bridge.schemas.case import CaseCreated, CaseStatus, ProgramEvaluation
from sme_bridge.schemas.evidence import EvidenceReference, SourceKind
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.services.eligibility import attach_verified_evidence, evaluate_program

router = APIRouter(prefix="/v1/cases", tags=["cases"])
demo_program_repository = InMemoryProgramRepository(
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
    ],
    evidence=[
        EvidenceReference(
            evidence_id=evidence_id,
            passage=passage,
            page=page,
            notice_version="sha256:synthetic-demo-v1",
            source_kind=SourceKind.SYNTHETIC_DEMO,
        )
        for evidence_id, passage, page in [
            ("EV-DEMO-REGION", "본사가 대전광역시에 소재한 기업", 1),
            ("EV-DEMO-EMPLOYEE", "상시 종업원 수가 10명 이하인 기업", 1),
            ("EV-DEMO-AGE", "판정 기준일 기준 업력 7년 이하인 기업", 2),
            ("EV-DEMO-PERIOD", "신청기간: 2026년 1월 1일부터 12월 31일까지", 2),
            ("EV-DEMO-INDUSTRY", "지원 업종 코드: J62", 3),
            ("EV-DEMO-SALES", "연 매출 10억원 미만 기업", 3),
            ("EV-DEMO-FUNDING", "운전자금 또는 운전·시설 복합자금 지원", 4),
        ]
    ],
)


def get_case_repository(request: Request) -> CaseRepository:
    """Resolve the repository installed during application startup."""
    repository = getattr(request.app.state, "case_repository", None)
    if repository is None:
        raise HTTPException(503, "Case storage is unavailable")
    return cast(CaseRepository, repository)


def get_program_repository(
    request: Request,
    source: Literal["official", "demo"] = "official",
) -> ProgramRepository:
    """Resolve the approved-program repository installed at startup."""
    name = "official_program_repository" if source == "official" else "program_repository"
    repository = getattr(request.app.state, name, None)
    if repository is None:
        raise HTTPException(503, "Program storage is unavailable")
    return cast(ProgramRepository, repository)


@router.post("", response_model=CaseCreated, status_code=status.HTTP_201_CREATED)
async def create_case(
    profile: BusinessProfile,
    repository: Annotated[CaseRepository, Depends(get_case_repository)],
    program_repository: Annotated[ProgramRepository, Depends(get_program_repository)],
    notices: Annotated[NoticeRepository, Depends(get_notice_repository)],
    source: Literal["official", "demo"] = "official",
    notice_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    ] = None,
) -> CaseCreated:
    """Validate and accept a synthetic business profile for later evaluation."""
    if notice_id is not None and source == "demo":
        raise HTTPException(422, "Select official source when specifying a notice ID")
    definitions = (
        await program_repository.find_candidates(profile, limit=3)
        if notice_id is None
        else [
            item
            for item in await program_repository.find_approved()
            if item.program_id == notice_id
        ]
    )
    evaluations = [evaluate_program(profile, definition) for definition in definitions]
    evidence_ids = list(
        dict.fromkeys(
            result.evidence_id for evaluation in evaluations for result in evaluation.rule_results
        )
    )
    available_evidence = await program_repository.find_evidence(evidence_ids)
    evaluations = [attach_verified_evidence(item, available_evidence) for item in evaluations]
    if source == "official":
        if notice_id is None:
            records = await notices.list_current(limit=100)
            records.sort(
                key=lambda item: (
                    -(
                        int(
                            profile.hq_region is not None
                            and profile.hq_region in item.snapshot.hashtags
                        )
                    ),
                    item.snapshot.notice_id,
                )
            )
        else:
            record = await notices.find(notice_id)
            if record is None:
                raise HTTPException(404, "Notice not found")
            records = [record]
        evaluated = {item.program_id for item in evaluations}
        for record in records:
            if len(evaluations) >= 3:
                break
            snapshot = record.snapshot
            if snapshot.notice_id in evaluated:
                continue
            evaluations.append(
                ProgramEvaluation(
                    program_id=snapshot.notice_id,
                    title=snapshot.title,
                    notice_version=f"sha256:{snapshot.version_hash}",
                    source_kind="OFFICIAL_NOTICE",
                    source_url=snapshot.url,
                    status=RuleStatus.UNKNOWN,
                    rule_results=[],
                    review_required=True,
                    review_reasons=["공고 원문에 근거한 자격 조건의 검토·승인이 필요합니다."],
                )
            )
    case = CaseCreated(
        case_id=f"case_{uuid4().hex}",
        status=(
            CaseStatus.REVIEW_PENDING
            if not evaluations or any(item.review_required for item in evaluations)
            else CaseStatus.RULE_CHECKED
        ),
        profile=profile,
        programs=evaluations,
        source=source,
        notes=(
            ["합성 공고를 이용한 데모 결과입니다."]
            if source == "demo"
            else ["저장된 공식 공고가 없습니다. 먼저 공고를 수집하세요."]
            if not evaluations
            else []
        ),
    )
    if idempotency_key is None:
        await repository.save(case)
        return case
    input_hash = hashlib.sha256(
        json.dumps(
            {
                "profile": profile.model_dump(mode="json"),
                "source": source,
                "notice_id": notice_id,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    try:
        return await repository.save_idempotent(case, idempotency_key, input_hash)
    except IdempotencyConflict as exc:
        raise HTTPException(409, "Idempotency-Key was reused with different input") from exc


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
