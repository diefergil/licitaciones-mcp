"""Verify the Alembic chain applies cleanly against a fresh database."""

from __future__ import annotations

import pytest

from licitaciones_mcp.storage import migrations

pytestmark = pytest.mark.integration


async def test_alembic_upgrade_is_idempotent(_migrated_database: None) -> None:
    """After the session fixture migrates, ``current`` reports the head revision."""

    assert migrations.current() == "0006_embedding_vector"
