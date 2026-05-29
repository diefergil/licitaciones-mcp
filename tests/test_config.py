"""Runtime settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from licitaciones_mcp.config import Settings


def test_search_backend_defaults_to_bm25() -> None:
    settings = Settings(_env_file=None)

    assert settings.search_backend == "bm25"


def test_search_backend_accepts_explicit_fts() -> None:
    settings = Settings(LICITACIONES_SEARCH_BACKEND="fts", _env_file=None)

    assert settings.search_backend == "fts"


def test_search_backend_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(LICITACIONES_SEARCH_BACKEND="hybrid", _env_file=None)
