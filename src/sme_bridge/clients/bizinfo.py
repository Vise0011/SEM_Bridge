"""Read-only client for the official Bizinfo support-program API."""

import asyncio
from types import TracebackType

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

BIZINFO_API_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"


class BizinfoClientError(RuntimeError):
    """Base error raised by the Bizinfo client boundary."""


class BizinfoContractError(BizinfoClientError):
    """Raised when Bizinfo returns data outside its documented contract."""


class BizinfoNotice(BaseModel):
    """Normalized subset of one official support-program notice."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    notice_id: str = Field(validation_alias=AliasChoices("pblancId", "seq"))
    title: str = Field(validation_alias=AliasChoices("pblancNm", "title"))
    url: str = Field(validation_alias=AliasChoices("pblancUrl", "link"))
    authority: str = Field(
        default="",
        validation_alias=AliasChoices("jrsdInsttNm", "author"),
    )
    executing_agency: str = Field(default="", validation_alias="excInsttNm")
    summary: str = Field(
        default="",
        validation_alias=AliasChoices("bsnsSumryCn", "description"),
    )
    category: str = Field(
        default="",
        validation_alias=AliasChoices("pldirSportRealmLclasCodeNm", "lcategory"),
    )
    published_at_raw: str = Field(
        default="",
        validation_alias=AliasChoices("creatPnttm", "pubDate"),
    )
    application_period_raw: str = Field(
        default="",
        validation_alias=AliasChoices("reqstBeginEndDe", "reqstDt"),
    )
    target: str = Field(default="", validation_alias="trgetNm")
    attachment_url: str = Field(default="", validation_alias="flpthNm")
    attachment_name: str = Field(default="", validation_alias="fileNm")
    hashtags_raw: str = Field(default="", validation_alias="hashTags")

    @property
    def hashtags(self) -> list[str]:
        return [tag.strip() for tag in self.hashtags_raw.split(",") if tag.strip()]


class BizinfoChannel(BaseModel):
    """Documented JSON channel wrapper."""

    model_config = ConfigDict(extra="ignore")

    title: str
    item: list[BizinfoNotice] = Field(default_factory=list)

    @field_validator("item", mode="before")
    @classmethod
    def normalize_single_item(cls, value: object) -> object:
        if isinstance(value, dict):
            return [value]
        return value


class BizinfoResponse(BaseModel):
    """Top-level JSON response returned by Bizinfo."""

    model_config = ConfigDict(extra="ignore")

    json_array: BizinfoChannel = Field(alias="jsonArray")


class BizinfoClient:
    """Async, read-only Bizinfo API client with bounded retries."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Bizinfo API key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    async def __aenter__(self) -> "BizinfoClient":
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

    async def fetch_finance_notices(
        self,
        *,
        count: int = 30,
        page: int = 1,
    ) -> list[BizinfoNotice]:
        """Fetch the latest finance notices using the documented category code 01."""
        if count < 1:
            raise ValueError("count must be at least 1")
        if page < 1:
            raise ValueError("page must be at least 1")

        params = {
            "crtfcKey": self._api_key,
            "dataType": "json",
            "searchCnt": str(count),
            "searchLclasId": "01",
            "pageUnit": str(count),
            "pageIndex": str(page),
        }
        response = await self._get_with_retry(params)
        try:
            payload = response.json()
            parsed = BizinfoResponse.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise BizinfoContractError("Bizinfo returned an invalid JSON contract") from exc
        return parsed.json_array.item

    async def _get_with_retry(self, params: dict[str, str]) -> httpx.Response:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get(BIZINFO_API_URL, params=params)
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.RequestError) or (exc.response.status_code >= 500)
                if not retryable or attempt == self._max_attempts:
                    raise BizinfoClientError("Bizinfo API request failed") from exc
                await asyncio.sleep(self._backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("unreachable")
