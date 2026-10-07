"""Validate a running localhost API without printing secrets or company inputs."""

import argparse
import asyncio
from uuid import uuid4

import httpx


async def main(port: int) -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
        for path in [
            "/",
            "/health",
            "/ready",
            "/docs",
            "/openapi.json",
            "/static/app.js",
            "/static/style.css",
            "/static/favicon.svg",
        ]:
            response = await client.get(path)
            response.raise_for_status()
            print(f"{path}: OK")
        response = await client.get("/v1/notices?limit=100")
        response.raise_for_status()
        notices = response.json()["items"]
        print(f"Stored official notices: {len(notices)}")
        pages = 0
        ocr_pages = 0
        for record in notices:
            snapshot = record["snapshot"]
            path = f"/v1/notices/{snapshot['notice_id']}"
            detail = await client.get(path)
            detail.raise_for_status()
            assert detail.json()["snapshot"] == snapshot
            versions = await client.get(path + "/versions")
            versions.raise_for_status()
            assert any(v["snapshot"] == snapshot for v in versions.json())
            page_offset = 0
            while True:
                response = await client.get(
                    path + "/passages", params={"limit": 100, "offset": page_offset}
                )
                response.raise_for_status()
                passages = response.json()["items"]
                assert all(p["notice_version_hash"] == snapshot["version_hash"] for p in passages)
                pages += len(passages)
                ocr_pages += sum(p["requires_ocr"] for p in passages)
                if len(passages) < 100:
                    break
                page_offset += 100
        print(f"Stored PDF pages: {pages}; OCR review flags: {ocr_pages}")
        unknown_id = "qa_missing_" + uuid4().hex
        for path, expected in [
            ("/v1/notices?limit=0", 422),
            ("/v1/notices?offset=-1", 422),
            (f"/v1/notices/{unknown_id}", 404),
            (f"/v1/notices/{unknown_id}/versions", 404),
            (f"/v1/notices/{unknown_id}/passages", 404),
            (f"/v1/cases/{unknown_id}", 404),
        ]:
            assert (await client.get(path)).status_code == expected
        absent = await client.get("/v1/notices", params={"q": unknown_id})
        absent.raise_for_status()
        assert absent.json()["items"] == []
        print("Read validation and unknown-resource responses: OK")
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
            saved.raise_for_status()
            assert saved.json() == result
            assert all(
                item["source_kind"]
                == ("OFFICIAL_NOTICE" if source == "official" else "SYNTHETIC_DEMO")
                for item in result["programs"]
            )
            print(f"{source} case saved and reloaded: {result['status']}")
        for updates, expected in [
            ({}, "PASS"),
            ({"employee_count": 11}, "FAIL"),
            ({"hq_region": None}, "UNKNOWN"),
            ({"query_date": "2027-01-01"}, "FAIL"),
        ]:
            response = await client.post("/v1/cases?source=demo", json={**profile, **updates})
            response.raise_for_status()
            result = response.json()["programs"][0]
            assert result["status"] == expected
            assert len(result["rule_results"]) == 7
            assert len(result["evidence"]) == 7 and not result["missing_evidence_ids"]
        print("Demo PASS / FAIL / UNKNOWN / expired period with seven citations: OK")
        for params, payload, headers in [
            ({"source": "demo"}, {**profile, "employee_count": -1}, {}),
            ({"source": "invalid"}, profile, {}),
            ({"source": "demo", "notice_id": "qa"}, profile, {}),
            ({"source": "demo"}, profile, {"Idempotency-Key": "invalid key"}),
        ]:
            response = await client.post("/v1/cases", params=params, json=payload, headers=headers)
            assert response.status_code == 422
        headers = {"Idempotency-Key": "qa-" + uuid4().hex}
        first = await client.post("/v1/cases?source=demo", json=profile, headers=headers)
        retry = await client.post("/v1/cases?source=demo", json=profile, headers=headers)
        first.raise_for_status()
        retry.raise_for_status()
        assert first.json() == retry.json()
        conflict = await client.post(
            "/v1/cases?source=demo", json={**profile, "employee_count": 9}, headers=headers
        )
        assert conflict.status_code == 409
        print("Invalid input, retry reuse and conflicting retry input: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    asyncio.run(main(args.port))
