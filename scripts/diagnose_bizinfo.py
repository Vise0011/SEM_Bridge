"""Print response shapes only; never print authentication keys or request URLs."""

import asyncio

import httpx

from sme_bridge.clients.bizinfo import BIZINFO_API_URL
from sme_bridge.config import get_settings


async def main() -> None:
    key = get_settings().bizinfo_api_key
    if key is None:
        print("KEY_MISSING")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            response = await client.get(
                BIZINFO_API_URL,
                params={
                    "crtfcKey": key.get_secret_value().strip(),
                    "dataType": "json",
                    "searchCnt": "5",
                    "searchLclasId": "01",
                    "pageUnit": "5",
                    "pageIndex": "1",
                },
            )
        except httpx.RequestError as exc:
            print(f"NETWORK_ERROR={type(exc).__name__}")
            return
    print(f"HTTP_STATUS={response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        print("NOT_JSON")
        return
    if not isinstance(payload, dict):
        print(f"PAYLOAD_TYPE={type(payload).__name__}")
        return
    items = payload.get("jsonArray")
    print(f"JSON_ARRAY_TYPE={type(items).__name__}")
    if isinstance(items, dict):
        print(f"WRAPPER_KEYS={sorted(items)}")
        items = items.get("item")
    if isinstance(items, list):
        print(f"ITEM_COUNT={len(items)}")
        if items and isinstance(items[0], dict):
            print(f"ITEM_FIELDS={[(k, type(v).__name__) for k, v in items[0].items()]}")


if __name__ == "__main__":
    asyncio.run(main())
