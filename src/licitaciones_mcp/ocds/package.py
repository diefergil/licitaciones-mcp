"""Build OCDS release packages from individual releases."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

OCDS_STANDARD_VERSION = "1.1"
OCDS_VERSION = OCDS_STANDARD_VERSION
DEFAULT_PUBLISHER_NAME = "licitaciones-mcp"
DEFAULT_PUBLISHER_URI = "https://github.com/diefergil/licitaciones-mcp"
DEFAULT_PUBLICATION_POLICY_URL = (
    "https://github.com/diefergil/licitaciones-mcp/blob/main/docs/ocds-mapping.md"
)
DEFAULT_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def build_release_package(
    releases: Iterable[dict[str, Any]],
    *,
    publisher_name: str = DEFAULT_PUBLISHER_NAME,
    publisher_uri: str = DEFAULT_PUBLISHER_URI,
    publication_policy: str = DEFAULT_PUBLICATION_POLICY_URL,
    license_url: str = DEFAULT_LICENSE_URL,
    ocds_version: str = OCDS_STANDARD_VERSION,
    uri: str | None = None,
) -> dict[str, Any]:
    """Wrap one or more releases in an OCDS release package."""

    release_list = list(releases)
    return {
        "uri": uri or "urn:licitaciones-mcp:release-package",
        "version": ocds_version,
        "publishedDate": datetime.now(UTC).isoformat(),
        "publisher": {"name": publisher_name, "uri": publisher_uri},
        "license": license_url,
        "publicationPolicy": publication_policy,
        "releases": release_list,
    }
