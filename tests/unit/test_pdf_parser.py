"""Tests for page-aware PDF parsing."""

import pymupdf
import pytest

from sme_bridge.documents import DocumentParseError, parse_pdf


def pdf_bytes(*, text: str | None = None) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if text is not None:
        page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_extracts_page_text_and_stable_hash() -> None:
    data = pdf_bytes(text="Official support notice eligibility condition")

    parsed = parse_pdf(data)

    assert parsed.page_count == 1
    assert "eligibility condition" in parsed.pages[0].text
    assert parsed.pages[0].requires_ocr is False
    assert len(parsed.sha256) == 64
    assert parse_pdf(data).sha256 == parsed.sha256


def test_flags_blank_page_as_requiring_ocr() -> None:
    parsed = parse_pdf(pdf_bytes())

    assert parsed.pages[0].requires_ocr is True
    assert parsed.ocr_required_pages == [1]


def test_rejects_non_pdf_content() -> None:
    with pytest.raises(DocumentParseError, match="not a PDF"):
        parse_pdf(b"<html>not a pdf</html>")


def test_enforces_page_limit() -> None:
    with pytest.raises(DocumentParseError, match="page limit"):
        parse_pdf(pdf_bytes(text="one page"), max_pages=0)
