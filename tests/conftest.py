"""Test resources are installed explicitly; production never silently uses test data."""

import pytest

from sme_bridge.api.routes.cases import demo_program_repository
from sme_bridge.main import app
from sme_bridge.repositories import (
    InMemoryCaseRepository,
    InMemoryDocumentRepository,
    InMemoryNoticeRepository,
    InMemoryProgramRepository,
)


@pytest.fixture(autouse=True)
def isolated_api_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "case_repository", InMemoryCaseRepository(), raising=False)
    monkeypatch.setattr(app.state, "program_repository", demo_program_repository, raising=False)
    monkeypatch.setattr(
        app.state, "official_program_repository", InMemoryProgramRepository([]), raising=False
    )
    monkeypatch.setattr(app.state, "notice_repository", InMemoryNoticeRepository(), raising=False)
    monkeypatch.setattr(
        app.state, "document_repository", InMemoryDocumentRepository(), raising=False
    )
