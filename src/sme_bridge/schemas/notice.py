"""Versioned notice snapshots produced by ingestion."""

from pydantic import BaseModel, ConfigDict, Field


class NoticeSnapshot(BaseModel):
    """Normalized immutable version of one Bizinfo notice."""

    model_config = ConfigDict(frozen=True)

    notice_id: str = Field(min_length=1)
    version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str
    url: str
    authority: str
    executing_agency: str
    summary: str
    category: str
    published_at_raw: str
    application_period_raw: str
    target: str
    attachment_url: str
    attachment_name: str
    hashtags: list[str]


class IngestionReport(BaseModel):
    """Summary of one bounded ingestion run."""

    fetched: int = Field(ge=0)
    new_versions: int = Field(ge=0)
    unchanged: int = Field(ge=0)
