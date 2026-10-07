"""Evidence references supporting approved eligibility conditions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceKind(StrEnum):
    """Trust category for a piece of source evidence."""

    OFFICIAL_NOTICE = "OFFICIAL_NOTICE"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


class EvidenceReference(BaseModel):
    """Immutable citation metadata returned with eligibility results."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    passage: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source_url: str | None = None
    notice_version: str = Field(min_length=1)
    source_kind: SourceKind
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
