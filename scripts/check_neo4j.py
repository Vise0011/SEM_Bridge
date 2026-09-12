"""Verify Neo4j connectivity and seed the approved demo graph."""

import asyncio
import sys

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from sme_bridge.config import get_settings
from sme_bridge.repositories import Neo4jProgramRepository


async def main() -> int:
    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
    )
    try:
        await driver.verify_connectivity()
        repository = Neo4jProgramRepository(driver)
        await repository.ensure_schema()
        await repository.seed_demo_program()
        count = await repository.count_programs()
        print(f"Neo4j connection and demo graph: OK ({count} program(s))")
    except (OSError, DriverError, Neo4jError):
        print(
            "Neo4j connection failed. Run 'docker compose up -d neo4j' first.",
            file=sys.stderr,
        )
        return 1
    finally:
        await driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
