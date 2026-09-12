"""Versioned Bizinfo notice-ingestion workflow."""

import hashlib
import json
from typing import Protocol

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.repositories.notices import NoticeRepository
from sme_bridge.schemas.notice import IngestionReport, NoticeSnapshot


class FinanceNoticeSource(Protocol):
    """Minimal read-only source contract required by ingestion."""

    async def fetch_finance_notices(
        self,
        *,
        count: int = 30,
        page: int = 1,
    ) -> list[BizinfoNotice]: ...


def build_notice_snapshot(notice: BizinfoNotice) -> NoticeSnapshot:
    """Build a stable snapshot whose hash changes only with normalized content."""
    normalized = {
        "notice_id": notice.notice_id,
        "title": notice.title,
        "url": notice.url,
        "authority": notice.authority,
        "executing_agency": notice.executing_agency,
        "summary": notice.summary,
        "category": notice.category,
        "published_at_raw": notice.published_at_raw,
        "application_period_raw": notice.application_period_raw,
        "target": notice.target,
        "attachment_url": notice.attachment_url,
        "attachment_name": notice.attachment_name,
        "hashtags": notice.hashtags,
    }
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    version_hash = hashlib.sha256(canonical).hexdigest()
    return NoticeSnapshot.model_validate({"version_hash": version_hash, **normalized})


async def ingest_finance_notices(
    source: FinanceNoticeSource,
    repository: NoticeRepository,
    *,
    count: int = 30,
) -> IngestionReport:
    """Fetch, version, and persist one bounded page of finance notices."""
    notices = await source.fetch_finance_notices(count=count, page=1)
    new_versions = 0
    for notice in notices:
        snapshot = build_notice_snapshot(notice)
        new_versions += int(await repository.save(snapshot))
    return IngestionReport(
        fetched=len(notices),
        new_versions=new_versions,
        unchanged=len(notices) - new_versions,
    )
