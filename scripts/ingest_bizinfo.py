"""Fetch and persist one bounded batch of official Bizinfo finance notices."""

import argparse
import asyncio
import sys

import asyncpg

from sme_bridge.clients import BizinfoClient, BizinfoClientError
from sme_bridge.config import Settings
from sme_bridge.documents import DocumentDownloadError, DocumentParseError, OfficialPdfDownloader
from sme_bridge.security.content import SanitizationError
from sme_bridge.services.documents import ingest_notice_document
from sme_bridge.services.ingestion import build_notice_snapshot
from sme_bridge.storage import open_storage


async def main(*, count: int = 30, documents: bool = False, backend: str | None = None) -> int:
    settings = Settings() if backend is None else Settings(storage_backend=backend)  # type: ignore[call-arg, arg-type]
    api_key = settings.bizinfo_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        print("BIZINFO_API_KEY is missing from .env.", file=sys.stderr)
        return 1

    try:
        async with open_storage(settings) as storage:
            async with BizinfoClient(api_key.get_secret_value()) as client:
                notices = await client.fetch_finance_notices(count=count)
            new_versions = 0
            outcomes: dict[str, int] = {}
            async with OfficialPdfDownloader() as downloader:
                for notice in notices:
                    snapshot = build_notice_snapshot(notice)
                    new_versions += int(await storage.notices.save(snapshot))
                    if not documents:
                        continue
                    if snapshot.attachment_name and not snapshot.attachment_name.lower().endswith(
                        ".pdf"
                    ):
                        outcome = "UNSUPPORTED_ATTACHMENT"
                    else:
                        try:
                            result = await ingest_notice_document(
                                snapshot, downloader, storage.documents
                            )
                            outcome = result.status
                        except DocumentDownloadError:
                            outcome = "DOWNLOAD_FAILED_OR_NON_PDF"
                        except (DocumentParseError, SanitizationError):
                            outcome = "PARSE_OR_SANITIZATION_FAILED"
                    outcomes[outcome] = outcomes.get(outcome, 0) + 1
                    print(f"{snapshot.notice_id}: {outcome}", flush=True)
    except BizinfoClientError:
        print("Bizinfo ingestion failed. Check the API key and network.", file=sys.stderr)
        return 1
    except (OSError, asyncpg.PostgresError):
        print("Storage is unavailable. Start PostgreSQL or use --backend sqlite.", file=sys.stderr)
        return 1

    print(
        f"Bizinfo ingestion: fetched={len(notices)}, "
        f"new_versions={new_versions}, unchanged={len(notices) - new_versions}"
    )
    if documents:
        print(f"Document outcomes: {outcomes}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--documents", action="store_true", help="Also download PDF attachments")
    parser.add_argument("--backend", choices=["sqlite", "postgres"])
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("--count must be between 1 and 100")
    raise SystemExit(
        asyncio.run(main(count=args.count, documents=args.documents, backend=args.backend))
    )
