"""Persistent local storage using SQLite, with the same application boundaries."""

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from sme_bridge.repositories.cases import IdempotencyConflict
from sme_bridge.repositories.programs import InMemoryProgramRepository
from sme_bridge.schemas.case import CaseCreated
from sme_bridge.schemas.document import DocumentPassage, ParsedPdf, StoredPassage
from sme_bridge.schemas.evidence import EvidenceReference
from sme_bridge.schemas.notice import NoticeRecord, NoticeSnapshot
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition
from sme_bridge.schemas.publication import PublishedProgram

T = TypeVar("T")
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_versions (
 notice_id TEXT, version_hash TEXT, payload TEXT NOT NULL, fetched_at TEXT NOT NULL,
 PRIMARY KEY (notice_id, version_hash));
CREATE TABLE IF NOT EXISTS notices (
 notice_id TEXT PRIMARY KEY, current_version_hash TEXT NOT NULL, title TEXT NOT NULL,
 updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
 notice_id TEXT, version_hash TEXT, sha256 TEXT, source_url TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY (notice_id, version_hash, sha256),
 FOREIGN KEY (notice_id, version_hash) REFERENCES notice_versions(notice_id, version_hash));
CREATE TABLE IF NOT EXISTS passages (
 notice_id TEXT, version_hash TEXT, sha256 TEXT, page_number INTEGER, text TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY (notice_id, version_hash, sha256, page_number),
 FOREIGN KEY (notice_id, version_hash, sha256)
 REFERENCES documents(notice_id, version_hash, sha256));
CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS case_requests (
 request_key TEXT PRIMARY KEY, input_hash TEXT NOT NULL,
 case_id TEXT NOT NULL REFERENCES cases(case_id));
CREATE TABLE IF NOT EXISTS current_documents (
 notice_id TEXT, version_hash TEXT, sha256 TEXT NOT NULL,
 PRIMARY KEY (notice_id,version_hash),
 FOREIGN KEY (notice_id,version_hash,sha256) REFERENCES documents(notice_id,version_hash,sha256));
CREATE TABLE IF NOT EXISTS publications (
 approval_hash TEXT PRIMARY KEY, notice_id TEXT NOT NULL, version_hash TEXT NOT NULL,
 payload TEXT NOT NULL, approved_at TEXT NOT NULL,
 FOREIGN KEY (notice_id, version_hash) REFERENCES notice_versions(notice_id, version_hash));
"""


class SQLiteStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    async def run(self, action: Callable[[sqlite3.Connection], T]) -> T:
        def execute() -> T:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path, timeout=20) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                return action(connection)

        return await asyncio.to_thread(execute)

    async def ensure_schema(self) -> None:
        await self.run(lambda connection: connection.executescript(SCHEMA) and None)


class SQLiteNoticeRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def save(self, snapshot: NoticeSnapshot) -> bool:
        def write(connection: sqlite3.Connection) -> bool:
            now = datetime.now(UTC).isoformat()
            result = connection.execute(
                "INSERT OR IGNORE INTO notice_versions VALUES (?,?,?,?)",
                (snapshot.notice_id, snapshot.version_hash, snapshot.model_dump_json(), now),
            )
            connection.execute(
                """INSERT INTO notices VALUES (?,?,?,?) ON CONFLICT(notice_id)
                DO UPDATE SET current_version_hash=excluded.current_version_hash,
                title=excluded.title, updated_at=excluded.updated_at""",
                (snapshot.notice_id, snapshot.version_hash, snapshot.title, now),
            )
            return result.rowcount == 1

        return await self.store.run(write)

    @staticmethod
    def _record(row: sqlite3.Row) -> NoticeRecord:
        return NoticeRecord(
            snapshot=NoticeSnapshot.model_validate_json(row["payload"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
        )

    async def find(self, notice_id: str, version_hash: str | None = None) -> NoticeRecord | None:
        row = await self.store.run(
            lambda connection: connection.execute(
                """SELECT v.* FROM notice_versions v WHERE v.notice_id=?
            AND v.version_hash=COALESCE(?,
             (SELECT current_version_hash FROM notices WHERE notice_id=?))""",
                (notice_id, version_hash, notice_id),
            ).fetchone()
        )
        return None if row is None else self._record(row)

    async def list_current(
        self,
        *,
        query: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> list[NoticeRecord]:
        rows = await self.store.run(
            lambda connection: connection.execute(
                """SELECT v.* FROM notices n JOIN notice_versions v
            ON n.notice_id=v.notice_id AND n.current_version_hash=v.version_hash
            WHERE instr(lower(n.title),lower(?))>0
            ORDER BY n.updated_at DESC,n.notice_id LIMIT ? OFFSET ?""",
                (query, limit, offset),
            ).fetchall()
        )
        return [self._record(row) for row in rows]

    async def list_versions(self, notice_id: str) -> list[NoticeRecord]:
        rows = await self.store.run(
            lambda connection: connection.execute(
                "SELECT * FROM notice_versions WHERE notice_id=? "
                "ORDER BY fetched_at DESC LIMIT 100",
                (notice_id,),
            ).fetchall()
        )
        return [self._record(row) for row in rows]


class SQLiteDocumentRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def save(
        self,
        *,
        notice_id: str,
        notice_version_hash: str,
        source_url: str,
        parsed: ParsedPdf,
        passages: list[DocumentPassage],
    ) -> bool:
        def write(connection: sqlite3.Connection) -> bool:
            key = (notice_id, notice_version_hash, parsed.sha256)
            result = connection.execute(
                "INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)",
                (*key, source_url, parsed.model_dump_json()),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO passages VALUES (?,?,?,?,?,?)",
                [(*key, item.page_number, item.text, item.model_dump_json()) for item in passages],
            )
            connection.execute(
                """INSERT INTO current_documents VALUES (?,?,?)
                ON CONFLICT(notice_id,version_hash) DO UPDATE SET sha256=excluded.sha256""",
                key,
            )
            return result.rowcount == 1

        return await self.store.run(write)

    async def search(
        self,
        *,
        notice_id: str,
        version_hash: str,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredPassage]:
        rows = await self.store.run(
            lambda connection: connection.execute(
                """SELECT p.*,d.source_url FROM passages p JOIN documents d
            USING (notice_id,version_hash,sha256) WHERE p.notice_id=? AND p.version_hash=?
            AND instr(lower(p.text),lower(?))>0 ORDER BY p.sha256,p.page_number LIMIT ? OFFSET ?""",
                (notice_id, version_hash, query, limit, offset),
            ).fetchall()
        )
        return [
            StoredPassage(
                **json.loads(row["payload"]),
                notice_id=notice_id,
                notice_version_hash=version_hash,
                pdf_sha256=row["sha256"],
                source_url=row["source_url"],
            )
            for row in rows
        ]

    async def current_hash(self, notice_id: str, version_hash: str) -> str | None:
        row = await self.store.run(
            lambda connection: connection.execute(
                "SELECT sha256 FROM current_documents WHERE notice_id=? AND version_hash=?",
                (notice_id, version_hash),
            ).fetchone()
        )
        return None if row is None else str(row["sha256"])


class SQLiteCaseRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def save(self, case: CaseCreated) -> None:
        await self.store.run(
            lambda connection: (
                connection.execute(
                    "INSERT INTO cases VALUES (?,?)",
                    (case.case_id, case.model_dump_json()),
                )
                and None
            )
        )

    async def find(self, case_id: str) -> CaseCreated | None:
        row = await self.store.run(
            lambda connection: connection.execute(
                "SELECT payload FROM cases WHERE case_id=?",
                (case_id,),
            ).fetchone()
        )
        return None if row is None else CaseCreated.model_validate_json(row["payload"])

    async def save_idempotent(
        self,
        case: CaseCreated,
        key: str,
        input_hash: str,
    ) -> CaseCreated:
        def write(connection: sqlite3.Connection) -> CaseCreated:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """SELECT r.input_hash,c.payload FROM case_requests r
                JOIN cases c USING(case_id) WHERE r.request_key=?""",
                (key,),
            ).fetchone()
            if previous is not None:
                if previous["input_hash"] != input_hash:
                    raise IdempotencyConflict("Retry key was reused for a different request")
                return CaseCreated.model_validate_json(previous["payload"])
            connection.execute(
                "INSERT INTO cases VALUES(?,?)", (case.case_id, case.model_dump_json())
            )
            connection.execute(
                "INSERT INTO case_requests VALUES(?,?,?)", (key, input_hash, case.case_id)
            )
            return case

        return await self.store.run(write)


class SQLitePublicationRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def publish(self, publication: PublishedProgram) -> None:
        def write(connection: sqlite3.Connection) -> None:
            connection.execute("BEGIN IMMEDIATE")
            payload = publication.model_dump_json()
            version = (publication.definition.notice_version or "").removeprefix("sha256:")
            row = connection.execute(
                "SELECT current_version_hash FROM notices WHERE notice_id=?",
                (publication.definition.program_id,),
            ).fetchone()
            if row is None or row[0] != version:
                raise ValueError("Notice changed during review; approve the current version")
            current_pdf = connection.execute(
                "SELECT sha256 FROM current_documents WHERE notice_id=? AND version_hash=?",
                (publication.definition.program_id, version),
            ).fetchone()
            if current_pdf is None or any(
                e.pdf_sha256 != current_pdf[0] for e in publication.evidence
            ):
                raise ValueError("PDF changed during review; approve the current PDF")
            connection.execute(
                "INSERT OR IGNORE INTO publications VALUES (?,?,?,?,?)",
                (
                    hashlib.sha256(payload.encode()).hexdigest(),
                    publication.definition.program_id,
                    version,
                    payload,
                    datetime.now(UTC).isoformat(),
                ),
            )

        await self.store.run(write)

    async def _publications(self) -> list[PublishedProgram]:
        rows = await self.store.run(
            lambda connection: connection.execute(
                """SELECT p.payload FROM publications p JOIN notices n
            ON n.notice_id=p.notice_id AND n.current_version_hash=p.version_hash
            ORDER BY p.approved_at DESC,p.approval_hash"""
            ).fetchall()
        )
        latest: dict[str, PublishedProgram] = {}
        for row in rows:
            item = PublishedProgram.model_validate_json(row["payload"])
            if item.definition.program_id in latest:
                continue
            latest[item.definition.program_id] = item
        current: list[PublishedProgram] = []
        for item in latest.values():
            version = (item.definition.notice_version or "").removeprefix("sha256:")
            current_pdf = await SQLiteDocumentRepository(self.store).current_hash(
                item.definition.program_id,
                version,
            )
            if not current_pdf or any(e.pdf_sha256 != current_pdf for e in item.evidence):
                continue
            current.append(item)
        return current

    async def find_approved(self) -> list[ProgramDefinition]:
        return [item.definition for item in await self._publications()]

    async def find_candidates(
        self,
        profile: BusinessProfile,
        limit: int = 3,
    ) -> list[ProgramDefinition]:
        repo = InMemoryProgramRepository(await self.find_approved())
        return await repo.find_candidates(profile, limit)

    async def find_evidence(self, evidence_ids: list[str]) -> list[EvidenceReference]:
        wanted = set(evidence_ids)
        return [
            evidence
            for item in await self._publications()
            for evidence in item.evidence
            if evidence.evidence_id in wanted
        ]
