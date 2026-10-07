"""Approve manually reviewed conditions after verifying every PDF citation."""

import argparse
import asyncio
from pathlib import Path

from pydantic import ValidationError

from sme_bridge.config import Settings
from sme_bridge.schemas.publication import PublicationDraft
from sme_bridge.services.publication import verify_publication
from sme_bridge.storage import open_storage


async def main(path: Path, backend: str) -> int:
    try:
        draft = PublicationDraft.model_validate_json(path.read_text(encoding="utf-8-sig"))
        settings = Settings(storage_backend=backend)  # type: ignore[call-arg, arg-type]
        async with open_storage(settings) as storage:
            publication = await verify_publication(draft, storage.notices, storage.documents)
            await storage.publications.publish(publication)
    except (ValueError, OSError, ValidationError) as exc:
        # Pydantic error messages may include full input; print only a safe category.
        print(f"Approval rejected: {type(exc).__name__}. Check version and exact PDF citations.")
        return 1
    print(f"Approved {draft.notice_id}; complete scope={draft.scope_complete}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--backend", choices=["sqlite", "postgres"], default="sqlite")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.file, args.backend)))
