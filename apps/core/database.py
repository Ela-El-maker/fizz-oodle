from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool

from apps.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_engine = create_async_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    poolclass=NullPool,
    future=True,
)

AsyncSessionLocal = sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
