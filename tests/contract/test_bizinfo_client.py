"""Contract tests for the read-only Bizinfo API client."""

import httpx
import pytest
import respx

from sme_bridge.clients.bizinfo import (
    BIZINFO_API_URL,
    BizinfoClient,
    BizinfoClientError,
    BizinfoContractError,
)


def response_payload(*, single_item: bool = False) -> dict[str, object]:
    item = {
        "pblancId": "PBLN_000000000000001",
        "pblancNm": "대전 중소기업 금융지원 공고",
        "pblancUrl": "https://www.bizinfo.go.kr/example",
        "jrsdInsttNm": "중소벤처기업부",
        "excInsttNm": "지역 수행기관",
        "bsnsSumryCn": "운전자금을 지원합니다.",
        "pldirSportRealmLclasCodeNm": "금융",
        "creatPnttm": "2026-09-01 09:00:00",
        "reqstBeginEndDe": "20260901 ~ 20260930",
        "trgetNm": "중소기업",
        "flpthNm": "https://www.bizinfo.go.kr/example.pdf",
        "fileNm": "공고문.pdf",
        "hashTags": "금융,대전,중소기업",
    }
    return {
        "jsonArray": {
            "title": "기업마당 지원사업정보",
            "item": item if single_item else [item],
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_finance_notices_uses_official_contract() -> None:
    route = respx.get(BIZINFO_API_URL).mock(
        return_value=httpx.Response(200, json=response_payload())
    )

    async with BizinfoClient("secret-key", backoff_seconds=0) as client:
        notices = await client.fetch_finance_notices(count=30, page=1)

    assert len(notices) == 1
    assert notices[0].notice_id == "PBLN_000000000000001"
    assert notices[0].hashtags == ["금융", "대전", "중소기업"]
    request_params = route.calls[0].request.url.params
    assert request_params["crtfcKey"] == "secret-key"
    assert request_params["dataType"] == "json"
    assert request_params["searchLclasId"] == "01"
    assert request_params["searchCnt"] == "30"


@pytest.mark.asyncio
@respx.mock
async def test_single_item_object_is_normalized_to_list() -> None:
    respx.get(BIZINFO_API_URL).mock(
        return_value=httpx.Response(200, json=response_payload(single_item=True))
    )

    async with BizinfoClient("secret-key", backoff_seconds=0) as client:
        notices = await client.fetch_finance_notices()

    assert [notice.notice_id for notice in notices] == ["PBLN_000000000000001"]


@pytest.mark.asyncio
@respx.mock
async def test_retry_is_bounded_for_server_errors() -> None:
    route = respx.get(BIZINFO_API_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json=response_payload()),
        ]
    )

    async with BizinfoClient("secret-key", backoff_seconds=0) as client:
        notices = await client.fetch_finance_notices()

    assert len(route.calls) == 3
    assert len(notices) == 1


@pytest.mark.asyncio
@respx.mock
async def test_client_does_not_retry_non_retryable_error() -> None:
    route = respx.get(BIZINFO_API_URL).mock(return_value=httpx.Response(401))

    async with BizinfoClient("secret-key", backoff_seconds=0) as client:
        with pytest.raises(BizinfoClientError, match="request failed"):
            await client.fetch_finance_notices()

    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_invalid_response_contract_is_rejected() -> None:
    respx.get(BIZINFO_API_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))

    async with BizinfoClient("secret-key", backoff_seconds=0) as client:
        with pytest.raises(BizinfoContractError, match="invalid JSON contract"):
            await client.fetch_finance_notices()


@respx.mock
async def test_live_array_contract_and_official_field_names() -> None:
    respx.get(BIZINFO_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonArray": [
                    {
                        "pblancId": "PBLN_LIVE",
                        "pblancNm": "실제 응답 형식",
                        "pblancUrl": "/web/example",
                        "printFlpthNm": "/cmm/fms/getFile.do?atchFileId=sample",
                        "printFileNm": "공고.pdf",
                        "hashtags": "금융,서울",
                    }
                ],
            },
        )
    )
    async with BizinfoClient(" abc123 ") as client:
        notices = await client.fetch_finance_notices()
    assert notices[0].attachment_name == "공고.pdf"
    assert notices[0].hashtags == ["금융", "서울"]
    assert notices[0].url == "https://www.bizinfo.go.kr/web/example"
    assert notices[0].attachment_url.startswith("https://www.bizinfo.go.kr/cmm/")


@respx.mock
async def test_empty_official_array_is_supported() -> None:
    respx.get(BIZINFO_API_URL).mock(return_value=httpx.Response(200, json={"jsonArray": []}))
    async with BizinfoClient("abc123") as client:
        assert await client.fetch_finance_notices() == []
