"""Security tests for the allowlisted PDF downloader."""

import httpx
import pytest
import respx

from sme_bridge.documents import DocumentDownloadError, OfficialPdfDownloader

OFFICIAL_PDF_URL = "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?id=test"


@pytest.mark.asyncio
@respx.mock
async def test_downloads_pdf_from_approved_host() -> None:
    data = b"%PDF-1.7\nsynthetic test bytes\n%%EOF"
    respx.get(OFFICIAL_PDF_URL).mock(return_value=httpx.Response(200, content=data))

    async with OfficialPdfDownloader() as downloader:
        downloaded = await downloader.download(OFFICIAL_PDF_URL)

    assert downloaded == data


@pytest.mark.asyncio
async def test_rejects_http_and_private_hosts_before_request() -> None:
    async with OfficialPdfDownloader() as downloader:
        with pytest.raises(DocumentDownloadError, match="allowlist"):
            await downloader.download("http://127.0.0.1/private.pdf")


@pytest.mark.asyncio
@respx.mock
async def test_revalidates_redirect_destination() -> None:
    respx.get(OFFICIAL_PDF_URL).mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/private.pdf"})
    )

    async with OfficialPdfDownloader() as downloader:
        with pytest.raises(DocumentDownloadError, match="allowlist"):
            await downloader.download(OFFICIAL_PDF_URL)


@pytest.mark.asyncio
@respx.mock
async def test_rejects_oversized_download() -> None:
    respx.get(OFFICIAL_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-" + b"x" * 50))

    async with OfficialPdfDownloader(max_bytes=10) as downloader:
        with pytest.raises(DocumentDownloadError, match="size limit"):
            await downloader.download(OFFICIAL_PDF_URL)


@pytest.mark.asyncio
@respx.mock
async def test_rejects_html_disguised_as_download() -> None:
    respx.get(OFFICIAL_PDF_URL).mock(
        return_value=httpx.Response(200, content=b"<html>login page</html>")
    )

    async with OfficialPdfDownloader() as downloader:
        with pytest.raises(DocumentDownloadError, match="not a PDF"):
            await downloader.download(OFFICIAL_PDF_URL)


@pytest.mark.asyncio
@respx.mock
async def test_rejects_invalid_content_length() -> None:
    respx.get(OFFICIAL_PDF_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-length": "not-a-number"},
            content=b"%PDF-1.7\n%%EOF",
        )
    )

    async with OfficialPdfDownloader() as downloader:
        with pytest.raises(DocumentDownloadError, match="content length"):
            await downloader.download(OFFICIAL_PDF_URL)
