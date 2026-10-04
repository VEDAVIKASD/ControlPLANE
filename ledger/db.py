"""Async SQLAlchemy engine/session setup.

DATABASE_URL drives the dialect:
postgresql+asyncpg://... in production,
sqlite+aiosqlite:///... in tests.

Both are exercised through the same ledger.models.Base metadata.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ledger.models import Base


_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_SQLITE_PATH = _ROOT / "demo" / "replayer" / "traffic.db"

DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{_DEFAULT_SQLITE_PATH}"


def normalize_database_url(url: str | None) -> str:
    """Normalize database URLs for SQLAlchemy async drivers.

    Neon provides PostgreSQL URLs using libpq-style parameters such as:

        sslmode=require
        channel_binding=require

    asyncpg expects SSL to be supplied as `ssl`, and does not accept
    `channel_binding` as a connection keyword through SQLAlchemy.

    Therefore:
        sslmode=require       -> ssl=require
        channel_binding=...   -> removed
    """

    # No DATABASE_URL -> use local SQLite database.
    if not url:
        return DEFAULT_DATABASE_URL

    # Keep existing SQLite test/dev behavior.
    if (
        url.startswith("sqlite+aiosqlite:///")
        and not url.startswith("sqlite+aiosqlite:////")
    ):
        rel_path = url[len("sqlite+aiosqlite:///") :]
        abs_path = (_ROOT / rel_path).resolve()
        return f"sqlite+aiosqlite:///{abs_path}"

    # Convert standard PostgreSQL URLs to the asyncpg SQLAlchemy dialect.
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]

    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    # Parse the query parameters safely instead of using string replacement.
    parts = urlsplit(url)

    query_params = parse_qsl(
        parts.query,
        keep_blank_values=True,
    )

    normalized_params: list[tuple[str, str]] = []

    for key, value in query_params:

        # libpq/PostgreSQL parameter -> asyncpg parameter.
        if key == "sslmode":
            key = "ssl"

        # Neon may provide:
        # channel_binding=require
        #
        # asyncpg.connect() does not accept this keyword.
        if key == "channel_binding":
            continue

        normalized_params.append((key, value))

    normalized_query = urlencode(normalized_params)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            normalized_query,
            parts.fragment,
        )
    )


def get_database_url() -> str:
    """Return the normalized DATABASE_URL."""

    return normalize_database_url(
        os.environ.get("DATABASE_URL")
    )


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Create the async SQLAlchemy engine."""

    norm_url = normalize_database_url(
        database_url or get_database_url()
    )

    connect_args: dict[str, object] = {}

    # Require TLS for remote PostgreSQL/Neon connections.
    #
    # Localhost connections are left alone so local development
    # continues to work without forced SSL.
    if (
        "asyncpg" in norm_url
        and "localhost" not in norm_url
        and "127.0.0.1" not in norm_url
    ):
        connect_args["ssl"] = "require"

    return create_async_engine(
        norm_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def get_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create the async SQLAlchemy session factory."""

    return async_sessionmaker(
        engine,
        expire_on_commit=False,
    )


async def init_models(engine: AsyncEngine) -> None:
    """Create tables if they don't exist.

    Used by tests and local development.
    Production deployments apply ledger/schema.sql explicitly.
    """

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )
