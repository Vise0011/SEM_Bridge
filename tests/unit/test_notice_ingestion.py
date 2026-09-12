"""Tests for immutable notice versioning and ingestion."""

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.repositories import InMemoryNoticeRepository
from sme_bridge.services.ingestion import build_notice_snapshot, ingest_finance_notices


def notice(*, summary: str = "운전자금을 지원합니다.") -> BizinfoNotice:
    return BizinfoNotice.model_validate(
        {
            "pblancId": "PBLN_TEST",
            "pblancNm": "대전 금융지원",
            "pblancUrl": "https://www.bizinfo.go.kr/example",
            "jrsdInsttNm": "중소벤처기업부",
            "bsnsSumryCn": summary,
            "pldirSportRealmLclasCodeNm": "금융",
            "reqstBeginEndDe": "20260901 ~ 20260930",
            "hashTags": "금융, 대전",
        }
    )


class FakeNoticeSource:
    def __init__(self, notices: list[BizinfoNotice]) -> None:
        self.notices = notices

    async def fetch_finance_notices(
        self,
        *,
        count: int = 30,
        page: int = 1,
    ) -> list[BizinfoNotice]:
        return self.notices[:count]


def test_snapshot_hash_is_stable_for_same_normalized_notice() -> None:
    first = build_notice_snapshot(notice())
    second = build_notice_snapshot(notice())

    assert first.version_hash == second.version_hash
    assert len(first.version_hash) == 64


def test_snapshot_hash_changes_when_notice_content_changes() -> None:
    first = build_notice_snapshot(notice(summary="기존 내용"))
    changed = build_notice_snapshot(notice(summary="변경된 내용"))

    assert first.version_hash != changed.version_hash


async def test_ingestion_does_not_duplicate_unchanged_version() -> None:
    source = FakeNoticeSource([notice()])
    repository = InMemoryNoticeRepository()

    first = await ingest_finance_notices(source, repository)
    second = await ingest_finance_notices(source, repository)

    assert first.model_dump() == {"fetched": 1, "new_versions": 1, "unchanged": 0}
    assert second.model_dump() == {"fetched": 1, "new_versions": 0, "unchanged": 1}
    assert len(repository.versions) == 1


async def test_ingestion_preserves_changed_version() -> None:
    repository = InMemoryNoticeRepository()
    await ingest_finance_notices(FakeNoticeSource([notice(summary="v1")]), repository)
    report = await ingest_finance_notices(
        FakeNoticeSource([notice(summary="v2")]),
        repository,
    )

    assert report.new_versions == 1
    assert len(repository.versions) == 2
    assert repository.current["PBLN_TEST"].summary == "v2"
