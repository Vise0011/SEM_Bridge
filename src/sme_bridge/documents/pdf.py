"""Secure downloading and page-aware extraction of official notice PDFs."""

import hashlib
from types import TracebackType
from urllib.parse import urljoin, urlparse

import httpx
import pymupdf

from sme_bridge.schemas.document import ParsedPdf, PdfPage

DEFAULT_ALLOWED_HOSTS = frozenset({"www.bizinfo.go.kr", "bizinfo.go.kr"})


class DocumentDownloadError(RuntimeError):
    """Raised when a source document cannot be downloaded safely."""


class DocumentParseError(RuntimeError):
    """Raised when downloaded bytes are not a supported readable PDF."""


class OfficialPdfDownloader:
    """Bounded downloader restricted to approved HTTPS source hosts."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
        max_bytes: int = 20 * 1024 * 1024,
        max_redirects: int = 3,
        timeout_seconds: float = 20.0,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._allowed_hosts = allowed_hosts
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    async def __aenter__(self) -> "OfficialPdfDownloader":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _validate_content(self, data: bytes) -> None:
        if not data.startswith(b"%PDF-"):
            raise DocumentDownloadError("downloaded content is not a PDF")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise DocumentDownloadError("invalid source URL port") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self._allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise DocumentDownloadError("source URL is not on the approved HTTPS allowlist")

    async def download(self, url: str) -> bytes:
        """Download one PDF while validating every redirect and size boundary."""
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            self._validate_url(current_url)
            try:
                async with self._client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if location is None or redirect_count == self._max_redirects:
                            raise DocumentDownloadError("invalid or excessive PDF redirect")
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError as exc:
                            raise DocumentDownloadError("invalid PDF content length") from exc
                        if declared_length > self._max_bytes:
                            raise DocumentDownloadError("PDF exceeds the download size limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_bytes:
                            raise DocumentDownloadError("PDF exceeds the download size limit")
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                raise DocumentDownloadError("PDF download failed") from exc

            data = bytes(body)
            self._validate_content(data)
            return data

        raise DocumentDownloadError("PDF redirect limit exceeded")


class OfficialAttachmentDownloader(OfficialPdfDownloader):
    """Same HTTPS and size controls, with HWPX ZIP containers also accepted."""

    def _validate_content(self, data: bytes) -> None:
        if not data.startswith((b"%PDF-", b"PK\x03\x04")):
            raise DocumentDownloadError("unsupported attachment: PDF or HWPX required")


def parse_pdf(
    data: bytes,
    *,
    max_pages: int = 200,
    minimum_text_characters: int = 20,
) -> ParsedPdf:
    """Extract normalized page text and flag pages that likely require OCR."""
    if not data.startswith(b"%PDF-"):
        raise DocumentParseError("content is not a PDF")

    try:
        document: pymupdf.Document = pymupdf.open(  # type: ignore[no-untyped-call]
            stream=data,
            filetype="pdf",
        )
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise DocumentParseError("PDF cannot be opened") from exc

    try:
        if document.needs_pass:
            raise DocumentParseError("encrypted PDF is not supported")
        if document.page_count < 1:
            raise DocumentParseError("PDF has no pages")
        if document.page_count > max_pages:
            raise DocumentParseError("PDF exceeds the page limit")

        pages: list[PdfPage] = []
        ocr_required_pages: list[int] = []
        for index in range(document.page_count):
            page: pymupdf.Page = document.load_page(index)  # type: ignore[no-untyped-call]
            raw_text: str = page.get_text(  # type: ignore[no-untyped-call]
                "text",
                sort=True,
            )
            text = raw_text.replace("\x00", "").strip()
            character_count = len(text)
            requires_ocr = character_count < minimum_text_characters
            page_number = index + 1
            if requires_ocr:
                ocr_required_pages.append(page_number)
            pages.append(
                PdfPage(
                    page_number=page_number,
                    text=text,
                    character_count=character_count,
                    requires_ocr=requires_ocr,
                )
            )

        return ParsedPdf(
            sha256=hashlib.sha256(data).hexdigest(),
            page_count=document.page_count,
            pages=pages,
            ocr_required_pages=ocr_required_pages,
        )
    finally:
        document.close()  # type: ignore[no-untyped-call]
