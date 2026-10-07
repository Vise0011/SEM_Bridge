"""Schemas for eligibility cases."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from sme_bridge.rules.models import RuleResult, RuleStatus
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.profile import BusinessProfile


class CaseStatus(StrEnum):
    """Initial subset of states used by the case workflow."""

    RECEIVED = "RECEIVED"
    RULE_CHECKED = "RULE_CHECKED"
    REVIEW_PENDING = "REVIEW_PENDING"


class ProgramEvaluation(BaseModel):
    """Condition-level eligibility result for one support program."""

    program_id: str
    status: RuleStatus
    rule_results: list[RuleResult]
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    review_required: bool = False
    evidence: list[EvidenceReference] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    title: str = ""
    notice_version: str | None = None
    source_kind: str = "SYNTHETIC_DEMO"
    review_reasons: list[str] = Field(default_factory=list)
    source_url: str | None = None


class CaseCreated(BaseModel):
    """Response returned after a profile is accepted."""

    case_id: str
    status: CaseStatus
    profile: BusinessProfile
    programs: list[ProgramEvaluation]
    source: Literal["official", "demo"] = "demo"
    notes: list[str] = Field(default_factory=list)
