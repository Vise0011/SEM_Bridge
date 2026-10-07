"""Validate a running localhost API without printing secrets or company inputs."""

import argparse
import asyncio

import httpx


async def main(port: int) -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
        for path in ["/", "/health", "/ready", "/docs", "/openapi.json", "/static/app.js"]:
            response = await client.get(path)
            response.raise_for_status()
            print(f"{path}: OK")
        response = await client.get("/v1/notices?limit=100")
        response.raise_for_status()
        notices = response.json()["items"]
        print(f"Stored official notices: {len(notices)}")
        pages = 0
        for record in notices:
            response = await client.get(
                f"/v1/notices/{record['snapshot']['notice_id']}/passages?limit=100"
            )
            response.raise_for_status()
            pages += len(response.json()["items"])
        print(f"Stored PDF pages (max 100 per notice): {pages}")
        profile = {
            "business_type": "CORPORATION",
            "established_date": "2023-03-15",
            "hq_region": "대전",
            "industry_code": "J62",
            "employee_count": 8,
            "annual_sales_band": "UNDER_1B_KRW",
            "certifications": [],
            "funding_purpose": "WORKING_CAPITAL",
            "query_date": "2026-10-07",
        }
        for source in ["official", "demo"]:
            response = await client.post(f"/v1/cases?source={source}", json=profile)
            response.raise_for_status()
            result = response.json()
            saved = await client.get(f"/v1/cases/{result['case_id']}")
            assert saved.json() == result
            assert all(
                item["source_kind"]
                == ("OFFICIAL_NOTICE" if source == "official" else "SYNTHETIC_DEMO")
                for item in result["programs"]
            )
            print(f"{source} case saved and reloaded: {result['status']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    asyncio.run(main(args.port))
