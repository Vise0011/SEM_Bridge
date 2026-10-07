"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from neo4j import AsyncGraphDatabase
from pydantic import BaseModel

from sme_bridge import __version__
from sme_bridge.api.routes.cases import demo_program_repository
from sme_bridge.api.routes.cases import router as cases_router
from sme_bridge.api.routes.notices import router as notices_router
from sme_bridge.config import Settings, get_settings
from sme_bridge.repositories import Neo4jProgramRepository
from sme_bridge.storage import open_storage


class HealthResponse(BaseModel):
    """Health-check response returned by the API."""

    status: str
    service: str
    version: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create shared database resources for the server process."""
    settings = getattr(application.state, "settings", None) or get_settings()
    application.state.storage_backend = settings.storage_backend
    async with open_storage(settings) as storage:
        application.state.case_repository = storage.cases
        application.state.notice_repository = storage.notices
        application.state.document_repository = storage.documents
        application.state.official_program_repository = storage.publications
        if settings.storage_backend == "sqlite":
            application.state.program_repository = demo_program_repository
            yield
            return
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the SME Bridge API application."""
    application = FastAPI(
        title="SME Bridge API",
        description="Evidence-based pre-screening for Korean SME support programs",
        version=__version__,
        lifespan=lifespan,
    )
    if settings is not None:
        application.state.settings = settings
    application.include_router(cases_router)
    application.include_router(notices_router)
    web_root = Path(__file__).parent / "web"
    application.mount("/static", StaticFiles(directory=web_root), name="static")

    @application.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="sme-bridge",
            version=__version__,
        )

    @application.get("/ready", tags=["system"])
    async def ready() -> dict[str, str]:
        try:
            await application.state.notice_repository.list_current(limit=1)
            await application.state.official_program_repository.find_approved()
            await application.state.program_repository.find_approved()
        except Exception as exc:
            raise HTTPException(503, "Storage is not ready") from exc
        return {"status": "ready", "storage": application.state.storage_backend}

    return application


app = create_app()
