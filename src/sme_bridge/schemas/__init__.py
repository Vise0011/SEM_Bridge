"""Validated data contracts used by SME Bridge."""

from sme_bridge.schemas.case import CaseCreated, CaseStatus, ProgramEvaluation
from sme_bridge.schemas.document import (
    DocumentIngestionResult,
    DocumentPassage,
    ParsedPdf,
    PdfPage,
)
from sme_bridge.schemas.evidence import EvidenceReference, SourceKind
from sme_bridge.schemas.profile import (
    AnnualSalesBand,
    BusinessProfile,
    BusinessType,
    FundingPurpose,
)
from sme_bridge.schemas.program import ProgramDefinition

__all__ = [
    "AnnualSalesBand",
    "BusinessProfile",
    "BusinessType",
    "CaseCreated",
    "CaseStatus",
    "DocumentIngestionResult",
    "DocumentPassage",
    "EvidenceReference",
    "FundingPurpose",
    "ParsedPdf",
    "PdfPage",
    "ProgramEvaluation",
    "ProgramDefinition",
    "SourceKind",
]
