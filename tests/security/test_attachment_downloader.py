"""HWPX additions keep the same source, size and redirect boundaries as PDFs."""

import httpx
import pytest
import respx

from sme_bridge.documents.pdf import DocumentDownloadError, OfficialAttachmentDownloader


@respx.mock
async def test_attachment_accepts_zip_magic_but_rejects_redirect_to_localhost():
    route = respx.get("https://www.bizinfo.go.kr/file").mock(
        return_value=httpx.Response(200, content=b"PK\x03\x04test")
    )
    async with OfficialAttachmentDownloader() as downloader:
        assert (await downloader.download("https://www.bizinfo.go.kr/file")).startswith(b"PK")
        route.mock(return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/file"}))
        with pytest.raises(DocumentDownloadError):
            await downloader.download("https://www.bizinfo.go.kr/file")


@respx.mock
@pytest.mark.parametrize(
    "content", [b"binary HWP", b"<html>error</html>", b"PK\x03\x04" + b"a" * 100]
)
async def test_attachment_rejects_format_or_size(content):
    respx.get("https://www.bizinfo.go.kr/file").mock(
        return_value=httpx.Response(200, content=content)
    )
    async with OfficialAttachmentDownloader(max_bytes=50) as downloader:
        with pytest.raises(DocumentDownloadError):
            await downloader.download("https://www.bizinfo.go.kr/file")
