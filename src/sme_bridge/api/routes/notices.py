"""Read-only APIs for versioned official notices and PDF evidence."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from sme_bridge.repositories import DocumentRepository, NoticeRepository
from sme_bridge.schemas.document import PassageList
from sme_bridge.schemas.notice import NoticeList, NoticeRecord

router = APIRouter(prefix="/v1/notices", tags=["official notices"])
Version = Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")]


def get_notice_repository(request: Request) -> NoticeRepository:
    repo = getattr(request.app.state, "notice_repository", None)
    if repo is None:
        raise HTTPException(503, "Notice storage is unavailable")
    return cast(NoticeRepository, repo)


def get_document_repository(request: Request) -> DocumentRepository:
    repo = getattr(request.app.state, "document_repository", None)
    if repo is None:
        raise HTTPException(503, "Document storage is unavailable")
    return cast(DocumentRepository, repo)


@router.get("", response_model=NoticeList)
async def list_notices(
    repository: Annotated[NoticeRepository, Depends(get_notice_repository)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> NoticeList:
    return NoticeList(
        items=await repository.list_current(query=q, limit=limit, offset=offset),
        limit=limit,
        offset=offset,
    )


@router.get("/{notice_id}", response_model=NoticeRecord)
async def get_notice(
    notice_id: str,
    repository: Annotated[NoticeRepository, Depends(get_notice_repository)],
    version: Version = None,
) -> NoticeRecord:
    record = await repository.find(notice_id, version)
    if record is None:
        raise HTTPException(404, "Notice version not found")
    return record


@router.get("/{notice_id}/versions", response_model=list[NoticeRecord])
async def get_versions(
    notice_id: str,
    repository: Annotated[NoticeRepository, Depends(get_notice_repository)],
) -> list[NoticeRecord]:
    if await repository.find(notice_id) is None:
        raise HTTPException(404, "Notice not found")
    return await repository.list_versions(notice_id)


@router.get("/{notice_id}/passages", response_model=PassageList)
async def search_passages(
    notice_id: str,
    notices: Annotated[NoticeRepository, Depends(get_notice_repository)],
    documents: Annotated[DocumentRepository, Depends(get_document_repository)],
    q: Annotated[str, Query(max_length=200)] = "",
    version: Version = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> PassageList:
    record = await notices.find(notice_id, version)
    if record is None:
        raise HTTPException(404, "Notice version not found")
    items = await documents.search(
        notice_id=notice_id,
        version_hash=record.snapshot.version_hash,
        query=q,
        limit=limit,
        offset=offset,
    )
    return PassageList(items=items, limit=limit, offset=offset)
