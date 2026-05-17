"""Dedupe key helpers."""

from __future__ import annotations

import hashlib

from licitaciones_mcp.core.models import Tender
from licitaciones_mcp.core.normalization import fold_text


def build_dedupe_key(tender: Tender) -> str:
    """Build a stable dedupe key for a tender."""

    if tender.source and tender.external_id:
        return f"{tender.source.value}:{tender.external_id}"

    title = fold_text(tender.title)
    buyer = fold_text(tender.buyer_name)
    date_part = tender.published_at.date().isoformat() if tender.published_at else ""
    url = tender.url or ""
    digest = hashlib.sha256("|".join([title, buyer, date_part, url]).encode()).hexdigest()
    return f"sha256:{digest}"


def attach_dedupe_key(tender: Tender) -> Tender:
    """Return a copy of the tender with a dedupe key set."""

    return tender.model_copy(update={"dedupe_key": tender.dedupe_key or build_dedupe_key(tender)})
