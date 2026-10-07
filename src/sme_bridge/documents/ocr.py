"""Killable local OCR preview; it does not replace or approve stored page evidence."""

import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path

import pymupdf

from sme_bridge.documents.pdf import DocumentParseError, parse_pdf
from sme_bridge.schemas.management import OcrPage
from sme_bridge.security.content import sanitize_untrusted_text


def ocr_available(tessdata: str) -> bool:
    return all(
        (Path(tessdata) / f"{language}.traineddata").is_file() for language in ["kor", "eng"]
    )


def _worker(data: bytes, pages: list[int], tessdata: str, pipe: Connection) -> None:
    try:
        result = []
        with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
            for number in pages:
                page = document.load_page(number - 1)
                if page.rect.width * page.rect.height * (150 / 72) ** 2 > 8_000_000:
                    raise ValueError("OCR image size limit")
                tp = page.get_textpage_ocr(
                    language="kor+eng", dpi=150, full=True, tessdata=tessdata
                )
                passage = sanitize_untrusted_text(page.get_text(textpage=tp, sort=True))
                result.append(
                    OcrPage(
                        page_number=number,
                        text=passage.text,
                        security_flags=[f.value for f in passage.security_flags],
                    ).model_dump()
                )
        pipe.send({"pages": result})
    except Exception:
        pipe.send({"error": "OCR_FAILED"})
    finally:
        pipe.close()


def preview_ocr(
    data: bytes, pages: list[int], tessdata: str, *, timeout: float = 60
) -> list[OcrPage]:
    if len(data) > 20 * 1024 * 1024:
        raise DocumentParseError("OCR input exceeds size limit")
    if not ocr_available(tessdata):
        raise DocumentParseError("OCR language data missing; run scripts/setup_ocr.py")
    parsed = parse_pdf(data)
    if (
        not 1 <= len(set(pages)) <= 3
        or len(set(pages)) != len(pages)
        or any(p < 1 or p > parsed.page_count for p in pages)
    ):
        raise ValueError("Select one to three valid distinct PDF pages")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker, args=(data, pages, str(Path(tessdata).resolve()), sender), daemon=True
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise DocumentParseError("OCR timed out")
        response = receiver.recv()
        if "error" in response:
            raise DocumentParseError("OCR failed or exceeded processing limits")
        return [OcrPage.model_validate(item) for item in response["pages"]]
    except EOFError as exc:
        raise DocumentParseError("OCR worker stopped") from exc
    finally:
        receiver.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join(5)
        process.close()
