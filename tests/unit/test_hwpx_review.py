"""HWPX boundaries and conservative, unapproved extraction."""

import io
import zipfile

import pytest

from sme_bridge.clients.bizinfo import BizinfoNotice
from sme_bridge.documents.hwpx import parse_hwpx
from sme_bridge.documents.pdf import DocumentParseError
from sme_bridge.schemas.document import StoredPassage
from sme_bridge.services.ingestion import build_notice_snapshot
from sme_bridge.services.review import suggest_rules


def hwpx(xml: bytes, name: str = "Contents/section0.xml", **other: bytes) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, xml)
        for key, value in other.items():
            archive.writestr(key, value)
    return data.getvalue()


def paragraph(text: str) -> bytes:
    return (
        '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:sec>"
    ).encode()


def passage(notice, text):
    return StoredPassage(
        notice_id=notice.notice_id,
        notice_version_hash=notice.version_hash,
        pdf_sha256="a" * 64,
        source_url="https://www.bizinfo.go.kr/test.pdf",
        page_number=1,
        text=text,
        character_count=len(text),
        requires_ocr=False,
    )


def test_hwpx_inline_runs_are_one_paragraph_and_explicit_sections():
    xml = paragraph("상시 근로자</hp:t><hp:t> 10명 미만")
    parsed = parse_hwpx(hwpx(xml))
    assert parsed.page_count == 1
    page = parsed.pages[0]
    assert page.text == "상시 근로자 10명 미만"
    assert page.document_kind == "HWPX" and page.location_kind == "SECTION"


@pytest.mark.parametrize(
    "data",
    [
        b"binary HWP",
        hwpx(paragraph("text"), name="../section0.xml"),
        hwpx(b"<!DOCTYPE x [<!ENTITY e 'boom'>]><x>&e;</x>"),
        hwpx("<!DOCTYPE x [<!ENTITY e 'boom'>]><x>&e;</x>".encode("utf-16")),
        hwpx(b"not XML"),
        hwpx(paragraph("a" * 500_000)),
    ],
)
def test_hwpx_rejects_unsupported_unsafe_or_excessive(data):
    with pytest.raises(DocumentParseError):
        parse_hwpx(data)


def test_hwpx_expansion_limit_and_empty_section():
    data = hwpx(paragraph("test"))
    with pytest.raises(DocumentParseError):
        parse_hwpx(data, max_expanded_bytes=10)
    assert parse_hwpx(hwpx(paragraph(""))).ocr_required_pages == [1]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("상시 근로자 10명 미만인 기업", {"maximum": 9}),
        ("종업원 수 10명 초과", {"minimum": 11}),
        ("종업원 수 10명 이상", {"minimum": 10}),
        ("본사가 대전광역시에 소재한 기업", {"allowed_regions": ["대전"]}),
        ("신청기간: 2026. 10. 01 ~ 2026. 11. 30", {"ends_on": "2026-11-30"}),
        ("접수기간: 2026. 10. 01 ~ 2026. 11. 30 18시", None),
        ("종업원 10명 이하, 단 예외 기업은 제외", None),
        ("종업원 0명 미만", None),
        ("신청기간: 2026. 11. 01 ~ 2026. 10. 01", None),
    ],
)
def test_suggestions_require_clear_safe_conditions(text, expected):
    notice = build_notice_snapshot(
        BizinfoNotice.model_validate(
            {"pblancId": "TEST", "pblancNm": "합성 검토 공고", "pblancUrl": "/test"}
        )
    )
    pages = [passage(notice, text)]
    result = suggest_rules(notice, pages)
    assert result.approved is False
    if expected is None:
        assert result.suggestions == []
    else:
        rule = result.suggestions[0].rule.model_dump(mode="json")
        for key, value in expected.items():
            assert rule[key] == value
        assert result.suggestions[0].citation.passage == text
    pages[0] = pages[0].model_copy(update={"requires_ocr": True})
    assert not suggest_rules(notice, pages).suggestions


def test_suggestions_skip_security_and_deduplicate():
    notice = build_notice_snapshot(
        BizinfoNotice.model_validate(
            {"pblancId": "TEST", "pblancNm": "합성 검토 공고", "pblancUrl": "/test"}
        )
    )
    text = "종업원 수 10명 이상\n종업원 수 10명 이상"
    pages = [passage(notice, text)]
    assert len(suggest_rules(notice, pages).suggestions) == 1
    from sme_bridge.security.content import SecurityFlag

    pages[0] = pages[0].model_copy(update={"security_flags": [SecurityFlag.PROMPT_OVERRIDE]})
    assert not suggest_rules(notice, pages).suggestions


async def test_hwpx_pipeline_preserves_sections_security_and_hash():
    from sme_bridge.repositories.documents import InMemoryDocumentRepository
    from sme_bridge.services.documents import ingest_notice_document

    data = hwpx(paragraph("상시 근로자 10명 이상인 기업을 지원합니다."))

    class Source:
        async def download(self, url):
            return data

    notice = build_notice_snapshot(
        BizinfoNotice.model_validate(
            {"pblancId": "TEST", "pblancNm": "합성 HWPX", "pblancUrl": "/test"}
        )
    ).model_copy(update={"attachment_url": "https://www.bizinfo.go.kr/test.hwpx"})
    repository = InMemoryDocumentRepository()
    result = await ingest_notice_document(notice, Source(), repository)
    assert result.status == "STORED"
    assert (await ingest_notice_document(notice, Source(), repository)).status == "UNCHANGED"
    pages = await repository.search(notice_id="TEST", version_hash=notice.version_hash)
    assert pages[0].location_kind == "SECTION"
    assert suggest_rules(notice, pages).suggestions[0].rule.minimum == 10
