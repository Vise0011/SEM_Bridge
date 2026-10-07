"""OCR validation and real OCR smoke when locally installed models are available."""

from pathlib import Path

import pymupdf
import pytest

from sme_bridge.documents.ocr import ocr_available, preview_ocr
from sme_bridge.documents.pdf import DocumentParseError


def image_pdf() -> bytes:
    source = pymupdf.open()
    page = source.new_page(width=600, height=300)
    page.insert_text((50, 100), "BRIDGE OCR TEST 123", fontsize=28)
    image = page.get_pixmap(dpi=150).tobytes("png")
    target = pymupdf.open()
    page = target.new_page(width=600, height=300)
    page.insert_image(page.rect, stream=image)
    data = target.tobytes()
    source.close()
    target.close()
    return data


def test_ocr_reports_missing_models_and_rejects_oversize(tmp_path):
    assert not ocr_available(str(tmp_path))
    with pytest.raises(DocumentParseError, match="language data missing"):
        preview_ocr(image_pdf(), [1], str(tmp_path))
    with pytest.raises(DocumentParseError, match="size limit"):
        preview_ocr(b"a" * (20 * 1024 * 1024 + 1), [1], str(tmp_path))


@pytest.mark.parametrize("pages", [[], [0], [2], [1, 1], [1, 2, 3, 4]])
def test_ocr_rejects_invalid_pages_before_starting_worker(tmp_path, pages):
    for lang in ["kor", "eng"]:
        (tmp_path / f"{lang}.traineddata").touch()
    with pytest.raises(ValueError, match="distinct"):
        preview_ocr(image_pdf(), pages, str(tmp_path))


def test_real_isolated_ocr_if_models_are_installed():
    tessdata = Path("data/local/tessdata")
    if not ocr_available(str(tessdata)):
        pytest.skip("Real OCR requires python scripts/setup_ocr.py")
    result = preview_ocr(image_pdf(), [1], str(tessdata))
    assert "BRIDGE" in result[0].text and "123" in result[0].text
    assert result[0].page_number == 1


def test_ocr_timeout_terminates_worker(tmp_path):
    for lang in ["kor", "eng"]:
        (tmp_path / f"{lang}.traineddata").touch()
    with pytest.raises(DocumentParseError, match="timed out"):
        preview_ocr(image_pdf(), [1], str(tmp_path), timeout=0)
