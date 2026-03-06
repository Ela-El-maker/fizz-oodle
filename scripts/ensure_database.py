#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlparse

import asyncpg


def _parse_db_url(url: str) -> dict:
    normalized = url.replace("postgresql+asyncpg://", "postgresql://")
    p = urlparse(normalized)
    if not p.hostname or not p.path:
        raise ValueError("Invalid DATABASE_URL")
    return {
        "user": p.username or "",
        "password": p.password or "",
        "host": p.hostname,
        "port": p.port or 5432,
        "database": p.path.lstrip("/"),
    }


async def _ensure(url: str) -> None:
    info = _parse_db_url(url)
    admin = await asyncpg.connect(
        user=info["user"],
        password=info["password"],
        host=info["host"],
        port=info["port"],
        database="postgres",
    )
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", info["database"])
        if not exists:
            await admin.execute(f'CREATE DATABASE "{info["database"]}"')
    finally:
        await admin.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: ensure_database.py <DATABASE_URL>", file=sys.stderr)
        return 1
    asyncio.run(_ensure(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

