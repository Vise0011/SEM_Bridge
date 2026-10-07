"""Parsed PDF document schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sme_bridge.security.content import SecurityFlag


class PdfPage(BaseModel):
    """Text extracted from one source page."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    text: str
    character_count: int = Field(ge=0)
    requires_ocr: bool
    document_kind: Literal["PDF", "HWPX"] = "PDF"
    location_kind: Literal["PAGE", "SECTION"] = "PAGE"


class ParsedPdf(BaseModel):
    """Immutable metadata and page text derived from a PDF."""

    model_config = ConfigDict(frozen=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    pages: list[PdfPage]
    ocr_required_pages: list[int]


class DocumentPassage(BaseModel):
    """Page text prepared for storage and later retrieval."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    text: str
    character_count: int = Field(ge=0)
    requires_ocr: bool
    document_kind: Literal["PDF", "HWPX"] = "PDF"
    location_kind: Literal["PAGE", "SECTION"] = "PAGE"
    trust_level: str = "UNTRUSTED_SOURCE"
    security_flags: list[SecurityFlag] = Field(default_factory=list)


class DocumentIngestionResult(BaseModel):
    """Outcome of downloading, parsing, and storing one notice attachment."""

    model_config = ConfigDict(frozen=True)

    notice_id: str
    status: Literal["STORED", "UNCHANGED", "NO_ATTACHMENT"]
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(default=0, ge=0)
    ocr_required_pages: list[int] = Field(default_factory=list)
    flagged_pages: int = Field(default=0, ge=0)


class StoredPassage(DocumentPassage):
    notice_id: str
    notice_version_hash: str
    pdf_sha256: str
    source_url: str


class PassageList(BaseModel):
    items: list[StoredPassage]
    limit: int
    offset: int
