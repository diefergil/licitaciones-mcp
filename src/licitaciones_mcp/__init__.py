"""Library and MCP server for Spain-first public tender workflows."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("licitaciones-mcp")
except PackageNotFoundError:
    __version__ = "0+unknown"
