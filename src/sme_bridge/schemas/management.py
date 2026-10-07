"""Local-only collection jobs and explicitly unapproved review suggestions."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sme_bridge.rules import ApprovedRule
from sme_bridge.schemas.publication import CitationInput


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=30, ge=1, le=100)
    documents: bool = True
    notice_id: str | None = Field(default=None, min_length=1, max_length=100)


class CollectionItem(BaseModel):
    notice_id: str
    status: str


class CollectionJob(BaseModel):
    job_id: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "INTERRUPTED"]
    request: CollectionRequest
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    processed: int = 0
    total: int = 0
    new_versions: int = 0
    items: list[CollectionItem] = Field(default_factory=list)
    error_code: str | None = None


class RuleSuggestion(BaseModel):
    rule: ApprovedRule
    citation: CitationInput
    location_kind: str
    warnings: list[str] = Field(
        default_factory=lambda: ["자동 초안입니다. 원문의 예외·기준일·범위를 직접 확인하세요."]
    )


class ReviewSuggestions(BaseModel):
    notice_id: str
    version_hash: str
    document_hash: str | None
    suggestions: list[RuleSuggestion]
    warnings: list[str]
    approved: Literal[False] = False


class OcrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pages: list[int] = Field(min_length=1, max_length=3)


class OcrPage(BaseModel):
    page_number: int
    text: str
    security_flags: list[str] = Field(default_factory=list)


class OcrPreview(BaseModel):
    notice_id: str
    document_hash: str
    pages: list[OcrPage]
    warning: str = (
        "OCR 참고 결과입니다. 오인식 가능성이 있으며 저장된 승인 근거를 대체하지 않습니다."
    )
