"""Loopback-only tools. Review validation/export NEVER publishes an approval."""

import asyncio
import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from sme_bridge.config import Settings
from sme_bridge.documents.ocr import ocr_available, preview_ocr
from sme_bridge.documents.pdf import (
    DocumentDownloadError,
    DocumentParseError,
    OfficialPdfDownloader,
)
from sme_bridge.repositories.jobs import ActiveCollectionError
from sme_bridge.schemas.management import (
    CollectionJob,
    CollectionRequest,
    OcrPreview,
    OcrRequest,
    ReviewSuggestions,
)
from sme_bridge.schemas.publication import PublicationDraft
from sme_bridge.services.collection import run_collection
from sme_bridge.services.publication import verify_publication
from sme_bridge.services.review import current_passages, suggest_rules
from sme_bridge.storage import Storage

router = APIRouter(prefix="/v1/manage", tags=["local review tools"])


def local_access(request: Request) -> None:
    if (
        request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or request.client is None
        or request.client.host not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise HTTPException(403, "Management is restricted to loopback requests")
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin management requests are not allowed")


def management_access(request: Request) -> Storage:
    local_access(request)
    settings: Settings = request.app.state.settings
    if not settings.local_management_enabled:
        raise HTTPException(403, "Local management is disabled")
    expected = request.app.state.management_token
    if not hmac.compare_digest(
        request.headers.get("x-bridge-token", "").encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(403, "Management token is required")
    return request.app.state.storage  # type: ignore[no-any-return]


StorageAccess = Annotated[Storage, Depends(management_access)]


@router.get("/status", dependencies=[Depends(local_access)])
async def management_status(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "enabled": settings.local_management_enabled,
        "ocr_available": ocr_available(settings.ocr_tessdata_path),
        "token": request.app.state.management_token if settings.local_management_enabled else None,
    }


@router.get("/jobs", response_model=list[CollectionJob])
async def list_jobs(storage: StorageAccess) -> list[CollectionJob]:
    return await storage.jobs.list()


@router.post("/jobs", response_model=CollectionJob, status_code=202)
async def start_collection(
    body: CollectionRequest, storage: StorageAccess, request: Request
) -> CollectionJob:
    settings: Settings = request.app.state.settings
    if body.notice_id is not None:
        if await storage.notices.find(body.notice_id) is None:
            raise HTTPException(404, "Stored notice not found")
    elif (
        settings.bizinfo_api_key is None or not settings.bizinfo_api_key.get_secret_value().strip()
    ):
        raise HTTPException(503, "Bizinfo API key is missing in the private server configuration")
    job = CollectionJob(job_id="job_" + secrets.token_hex(16), status="QUEUED", request=body)
    try:
        await storage.jobs.begin(job)
    except ActiveCollectionError as exc:
        raise HTTPException(409, "A collection job is already active") from exc
    task = asyncio.create_task(run_collection(job, storage, settings))
    request.app.state.collection_tasks.add(task)
    task.add_done_callback(request.app.state.collection_tasks.discard)
    return job


@router.get("/notices/{notice_id}/suggestions", response_model=ReviewSuggestions)
async def suggestions(notice_id: str, storage: StorageAccess) -> ReviewSuggestions:
    record = await storage.notices.find(notice_id)
    if record is None:
        raise HTTPException(404, "Stored notice not found")
    try:
        pages = await current_passages(storage.documents, record.snapshot)
    except ValueError as exc:
        raise HTTPException(409, "Too many historical passages") from exc
    return suggest_rules(record.snapshot, pages)


@router.post("/review/validate", response_model=PublicationDraft)
async def validate_review(body: PublicationDraft, storage: StorageAccess) -> PublicationDraft:
    try:
        await verify_publication(body, storage.notices, storage.documents)
    except ValueError as exc:
        raise HTTPException(
            409, "Review rejected: check current document, exact quote and OCR/security flags"
        ) from exc
    return body


@router.post("/notices/{notice_id}/ocr", response_model=OcrPreview)
async def ocr_notice(
    notice_id: str, body: OcrRequest, storage: StorageAccess, request: Request
) -> OcrPreview:
    settings: Settings = request.app.state.settings
    if not ocr_available(settings.ocr_tessdata_path):
        raise HTTPException(503, "OCR language data missing. Run python scripts/setup_ocr.py")
    if request.app.state.ocr_lock.locked():
        raise HTTPException(409, "An OCR preview is already running")
    async with request.app.state.ocr_lock:
        record = await storage.notices.find(notice_id)
        if record is None:
            raise HTTPException(404, "Stored notice not found")
        snapshot = record.snapshot
        if snapshot.attachment_name and not snapshot.attachment_name.lower().endswith(".pdf"):
            raise HTTPException(422, "OCR preview supports PDFs only")
        try:
            async with OfficialPdfDownloader() as downloader:
                data = await downloader.download(snapshot.attachment_url)
            current = await storage.documents.current_hash(notice_id, snapshot.version_hash)
            if hashlib.sha256(data).hexdigest() != current:
                raise HTTPException(
                    409, "Source PDF changed or was not collected; re-collect it first"
                )
            pages = await asyncio.to_thread(
                preview_ocr, data, body.pages, settings.ocr_tessdata_path
            )
        except ValueError as exc:
            raise HTTPException(422, "Select one to three distinct valid PDF pages") from exc
        except (DocumentDownloadError, DocumentParseError) as exc:
            raise HTTPException(
                502, "OCR download or processing failed; check source and limits"
            ) from exc
        latest = await storage.notices.find(notice_id)
        if (
            latest is None
            or latest.snapshot.version_hash != snapshot.version_hash
            or await storage.documents.current_hash(notice_id, snapshot.version_hash) != current
        ):
            raise HTTPException(409, "Stored source changed during OCR; retry with current source")
        return OcrPreview(notice_id=notice_id, document_hash=current, pages=pages)
