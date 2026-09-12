"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from neo4j import AsyncGraphDatabase
from pydantic import BaseModel

from sme_bridge import __version__
from sme_bridge.api.routes.cases import router as cases_router
from sme_bridge.config import get_settings
from sme_bridge.repositories import (
    Neo4jProgramRepository,
    PostgresCaseRepository,
    PostgresDocumentRepository,
    PostgresNoticeRepository,
)


class HealthResponse(BaseModel):
    """Health-check response returned by the API."""

    status: str
    service: str
    version: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create shared database resources for the server process."""
    settings = get_settings()
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
    case_repository = PostgresCaseRepository(pool)
    await case_repository.ensure_schema()
    application.state.case_repository = case_repository
    notice_repository = PostgresNoticeRepository(pool)
    await notice_repository.ensure_schema()
    application.state.notice_repository = notice_repository
    document_repository = PostgresDocumentRepository(pool)
    await document_repository.ensure_schema()
    application.state.document_repository = document_repository

    neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
    )
    try:
        await neo4j_driver.verify_connectivity()
        program_repository = Neo4jProgramRepository(neo4j_driver)
        await program_repository.ensure_schema()
        await program_repository.seed_demo_program()
        application.state.program_repository = program_repository
        yield
    finally:
        await neo4j_driver.close()
        await pool.close()


def create_app() -> FastAPI:
    """Create and configure the SME Bridge API application."""
    application = FastAPI(
        title="SME Bridge API",
        description="Evidence-based pre-screening for Korean SME support programs",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(cases_router)

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="sme-bridge",
            version=__version__,
        )

    return application


app = create_app()
