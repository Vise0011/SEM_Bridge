"""Fetch a small read-only sample from the official Bizinfo API."""

import asyncio
import sys

from sme_bridge.clients import BizinfoClient, BizinfoClientError
from sme_bridge.clients.bizinfo import BizinfoContractError
from sme_bridge.config import get_settings


async def main() -> int:
    api_key = get_settings().bizinfo_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        print(
            "BIZINFO_API_KEY is missing. Add the issued key to your private .env file.",
            file=sys.stderr,
        )
        return 1

    try:
        async with BizinfoClient(api_key.get_secret_value()) as client:
            notices = await client.fetch_finance_notices(count=5)
    except BizinfoContractError:
        print(
            "Bizinfo response format is unsupported. Run scripts/diagnose_bizinfo.py.",
            file=sys.stderr,
        )
        return 1
    except BizinfoClientError:
        print(
            "Bizinfo API check failed. Verify the issued key and network connection.",
            file=sys.stderr,
        )
        return 1

    notice_ids = ", ".join(notice.notice_id for notice in notices)
    print(f"Bizinfo finance notices: OK ({len(notices)} item(s))")
    print(f"Notice IDs: {notice_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
