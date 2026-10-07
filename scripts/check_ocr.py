"""Exercise the real killable OCR worker with a generated image-only PDF."""

import pymupdf

from sme_bridge.config import Settings
from sme_bridge.documents.ocr import ocr_available, preview_ocr


def main() -> int:
    settings = Settings()
    if not ocr_available(settings.ocr_tessdata_path):
        print("OCR data missing: python scripts/setup_ocr.py")
        return 1
    with pymupdf.open() as source, pymupdf.open() as target:
        page = source.new_page(width=600, height=300)
        page.insert_text((50, 100), "BRIDGE OCR TEST 123", fontsize=28)
        image = page.get_pixmap(dpi=150).tobytes("png")
        scanned = target.new_page(width=600, height=300)
        scanned.insert_image(scanned.rect, stream=image)
        result = preview_ocr(target.tobytes(), [1], settings.ocr_tessdata_path)
    if not result or "BRIDGE" not in result[0].text or "123" not in result[0].text:
        print("OCR smoke failed: expected synthetic text was not recognized")
        return 1
    print("Real isolated OCR image-only PDF: OK (Korean and English models loaded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
