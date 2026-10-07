"""Bounded HWPX text extraction; section indices are NOT physical page numbers."""

import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree

from sme_bridge.documents.pdf import DocumentParseError
from sme_bridge.schemas.document import ParsedPdf, PdfPage

PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION_PATTERN = re.compile(r"Contents/section([0-9]+)\.xml$")


def parse_hwpx(data: bytes, *, max_expanded_bytes: int = 20_000_000) -> ParsedPdf:
    """Never extract files, follow links, evaluate XML entities or execute macros."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or len({e.filename for e in entries}) != len(entries):
                raise DocumentParseError("invalid or excessive HWPX entries")
            if any(e.flag_bits & 1 for e in entries):
                raise DocumentParseError("encrypted HWPX is not supported")
            if sum(e.file_size for e in entries) > max_expanded_bytes:
                raise DocumentParseError("HWPX expanded size limit exceeded")
            if any(e.file_size > 200 * max(1, e.compress_size) for e in entries):
                raise DocumentParseError("HWPX compression ratio limit exceeded")
            sections = sorted(
                [(int(m[1]), e) for e in entries if (m := SECTION_PATTERN.fullmatch(e.filename))],
                key=lambda item: item[0],
            )
            if not sections or len(sections) > 200:
                raise DocumentParseError("HWPX sections missing or excessive")
            pages = []
            for index, (_, entry) in enumerate(sections, start=1):
                xml = archive.read(entry)
                normalized_xml = xml.replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in normalized_xml or b"<!ENTITY" in normalized_xml:
                    raise DocumentParseError("HWPX XML entities are not permitted")
                root = ElementTree.fromstring(xml)
                paragraphs = list(root.iter(f"{{{PARAGRAPH_NS}}}p"))
                text = "\n".join(
                    "".join("".join(t.itertext()) for t in p.iter(f"{{{PARAGRAPH_NS}}}t"))
                    for p in paragraphs
                ).strip()
                if len(text) > 200_000:
                    raise DocumentParseError("HWPX section text limit exceeded")
                pages.append(
                    PdfPage(
                        page_number=index,
                        text=text,
                        character_count=len(text),
                        requires_ocr=not bool(text),
                        document_kind="HWPX",
                        location_kind="SECTION",
                    )
                )
    except (
        zipfile.BadZipFile,
        ElementTree.ParseError,
        RuntimeError,
        NotImplementedError,
        OSError,
    ) as exc:
        raise DocumentParseError("HWPX cannot be parsed safely") from exc
    return ParsedPdf(
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=len(pages),
        pages=pages,
        ocr_required_pages=[p.page_number for p in pages if p.requires_ocr],
    )
