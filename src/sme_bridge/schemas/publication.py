"""Human-reviewed conditions with citations bound to an immutable PDF version."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sme_bridge.rules import ApprovedRule
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.program import ProgramDefinition


class CitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=200)
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    passage: str = Field(min_length=5, max_length=5000)


class PublicationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_id: str = Field(min_length=1, max_length=100)
    version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=100)
    scope_complete: bool = False
    conditions: list[ApprovedRule] = Field(min_length=1, max_length=100)
    citations: list[CitationInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> "PublicationDraft":
        ids = [item.evidence_id for item in self.citations]
        prefix = f"{self.notice_id}:{self.version_hash}:"
        if len(set(ids)) != len(ids) or any(not item.startswith(prefix) for item in ids):
            raise ValueError(
                "citation IDs must be unique and prefixed with notice_id:version_hash:"
            )
        if {item.evidence_id for item in self.conditions} != set(ids):
            raise ValueError("every condition must reference exactly the supplied citations")
        return self


class PublishedProgram(BaseModel):
    definition: ProgramDefinition
    evidence: list[EvidenceReference]
    approved_by: str
