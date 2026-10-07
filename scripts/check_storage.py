"""Report aggregate local storage counts without displaying credentials or source text."""

import asyncio

from sme_bridge.config import Settings
from sme_bridge.repositories.sqlite import SQLiteStore


async def main() -> None:
    settings = Settings(storage_backend="sqlite")
    store = SQLiteStore(settings.sqlite_path)
    await store.ensure_schema()
    for table in ["notices", "notice_versions", "documents", "passages", "cases", "publications"]:
        count = await store.run(
            lambda connection, table=table: connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
        )
        print(f"{table}={count}")


if __name__ == "__main__":
    asyncio.run(main())
