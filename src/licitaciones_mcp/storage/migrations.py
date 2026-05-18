"""Helpers to invoke Alembic from CLI / application code.

The Alembic environment ships inside the package at
``licitaciones_mcp/_migrations`` so the same migrations are usable from
editable installs, wheels and Docker images alike. No external
``alembic.ini`` is required: configuration is assembled in memory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from threading import Thread
from typing import Any, TypeVar, cast

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from licitaciones_mcp.config import Settings, get_settings

_SCRIPT_LOCATION = Path(__file__).resolve().parent.parent / "_migrations"
_T = TypeVar("_T")


def _make_config(settings: Settings | None = None) -> Config:
    """Build an in-memory Alembic ``Config`` for the configured database."""

    cfg = Config()
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", (settings or get_settings()).database_url)
    return cfg


def upgrade(revision: str = "head", *, settings: Settings | None = None) -> None:
    """Run ``alembic upgrade <revision>`` against the configured database."""

    command.upgrade(_make_config(settings), revision)


def downgrade(revision: str, *, settings: Settings | None = None) -> None:
    """Run ``alembic downgrade <revision>`` against the configured database."""

    command.downgrade(_make_config(settings), revision)


def stamp(revision: str = "head", *, settings: Settings | None = None) -> None:
    """Stamp the database with a revision without running migrations."""

    command.stamp(_make_config(settings), revision)


def revision(message: str, *, autogenerate: bool = False, settings: Settings | None = None) -> None:
    """Create a new Alembic revision."""

    command.revision(_make_config(settings), message=message, autogenerate=autogenerate)


async def _current_async(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
            return str(row[0]) if row else None
    finally:
        await engine.dispose()


def _run_coro_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[_T] = []
    errors: list[BaseException] = []

    def _target() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def current(*, settings: Settings | None = None) -> str | None:
    """Return the current database revision."""

    cfg = _make_config(settings)
    return _run_coro_sync(_current_async(cast(str, cfg.get_main_option("sqlalchemy.url"))))
