"""Bounded background collection, with safe durable per-notice outcomes."""

import asyncio
from datetime import UTC, datetime

from sme_bridge.clients import BizinfoClient, BizinfoClientError
from sme_bridge.config import Settings
from sme_bridge.documents.pdf import (
    DocumentDownloadError,
    DocumentParseError,
    OfficialAttachmentDownloader,
)
from sme_bridge.schemas.management import CollectionItem, CollectionJob
from sme_bridge.security.content import SanitizationError
from sme_bridge.services.documents import ingest_notice_document
from sme_bridge.services.ingestion import build_notice_snapshot
from sme_bridge.storage import Storage


async def run_collection(job: CollectionJob, storage: Storage, settings: Settings) -> None:
    try:
        job.status = "RUNNING"
        await storage.jobs.save(job)
        if job.request.notice_id:
            record = await storage.notices.find(job.request.notice_id)
            snapshots = [] if record is None else [record.snapshot]
        else:
            key = settings.bizinfo_api_key
            if key is None or not key.get_secret_value().strip():
                raise ValueError("API_KEY_MISSING")
            async with BizinfoClient(key.get_secret_value()) as client:
                notices = await client.fetch_finance_notices(count=job.request.count)
            snapshots = [build_notice_snapshot(n) for n in notices]
        job.total = len(snapshots)
        async with OfficialAttachmentDownloader() as downloader:
            for snapshot in snapshots:
                job.new_versions += int(await storage.notices.save(snapshot))
                outcome = "METADATA_STORED"
                if job.request.documents:
                    if snapshot.attachment_name and not snapshot.attachment_name.lower().endswith(
                        (".pdf", ".hwpx")
                    ):
                        outcome = "FORMAT_CONVERSION_REQUIRED"
                    else:
                        try:
                            result = await ingest_notice_document(
                                snapshot, downloader, storage.documents
                            )
                            outcome = result.status
                        except DocumentDownloadError:
                            outcome = "DOWNLOAD_FAILED_OR_UNSUPPORTED"
                        except (DocumentParseError, SanitizationError):
                            outcome = "PARSE_OR_SECURITY_LIMIT"
                job.items.append(CollectionItem(notice_id=snapshot.notice_id, status=outcome))
                job.processed += 1
                await storage.jobs.save(job)
        job.status = (
            "PARTIAL"
            if any(
                item.status not in {"STORED", "UNCHANGED", "NO_ATTACHMENT", "METADATA_STORED"}
                for item in job.items
            )
            else "SUCCEEDED"
        )
    except asyncio.CancelledError:
        job.status = "INTERRUPTED"
        job.error_code = "SERVER_STOPPED"
        raise
    except BizinfoClientError:
        job.status, job.error_code = "FAILED", "BIZINFO_API_FAILED"
    except Exception:
        # Never persist exception strings: upstream requests may contain credentials.
        job.status, job.error_code = "FAILED", "STORAGE_OR_PROCESSING_FAILED"
    finally:
        job.finished_at = datetime.now(UTC)
        await storage.jobs.save(job)
