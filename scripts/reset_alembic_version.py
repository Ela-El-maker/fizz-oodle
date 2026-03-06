from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def _drop_version_table(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await engine.dispose()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/reset_alembic_version.py <DATABASE_URL>", file=sys.stderr)
        return 2

    asyncio.run(_drop_version_table(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
