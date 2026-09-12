"""Approved support-program definitions."""

from pydantic import BaseModel, ConfigDict, Field

from sme_bridge.rules import ApprovedRule


class ProgramDefinition(BaseModel):
    """A published program and its human-approved deterministic rules."""

    model_config = ConfigDict(frozen=True)

    program_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    conditions: list[ApprovedRule] = Field(min_length=1)
