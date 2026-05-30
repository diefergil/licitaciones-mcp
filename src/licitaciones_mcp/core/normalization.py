"""Normalization helpers for tender data."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation

from licitaciones_mcp.core.models import TenderStatus

CPV_RE = re.compile(r"\b(\d{8})(?:-\d)?\b")
CPV_PREFIX_RE = re.compile(r"^\d{2,8}$")


def normalize_text(value: str | None) -> str | None:
    """Collapse whitespace and strip a text value."""

    if value is None:
        return None
    normalized = " ".join(value.replace("\xa0", " ").split())
    return normalized or None


def fold_text(value: str | None) -> str:
    """Return lowercase ASCII-folded text for matching."""

    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def normalize_cpv_code(value: str) -> str | None:
    """Return an 8-digit CPV code when one can be extracted."""

    match = CPV_RE.search(value.strip())
    if not match:
        return None
    return match.group(1)


def normalize_cpv_codes(values: list[str] | str | None) -> list[str]:
    """Normalize a list or comma-separated string of CPV codes."""

    if values is None:
        return []
    raw_values = values.split(",") if isinstance(values, str) else values
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_values:
        code = normalize_cpv_code(str(raw))
        if code and code not in seen:
            seen.add(code)
            result.append(code)
    return result


def normalize_cpv_prefix(value: str) -> str | None:
    """Return a 2-8 digit CPV prefix suitable for family/sector filters."""

    normalized = str(value).strip().replace("*", "")
    if normalized.endswith(".0"):
        normalized = normalized[:-2]
    normalized = "".join(char for char in normalized if char.isdigit())
    if not CPV_PREFIX_RE.fullmatch(normalized):
        return None
    return normalized


def normalize_cpv_prefixes(values: list[str] | str | None) -> list[str]:
    """Normalize a list or comma-separated string of CPV prefixes."""

    if values is None:
        return []
    raw_values = values.split(",") if isinstance(values, str) else values
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_values:
        prefix = normalize_cpv_prefix(str(raw))
        if prefix and prefix not in seen:
            seen.add(prefix)
            result.append(prefix)
    return result


def parse_datetime(value: str | date | datetime | None) -> datetime | None:
    """Parse common date/datetime values into timezone-aware datetimes."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)

    raw = value.strip()
    if not raw:
        return None

    candidates = [
        raw,
        raw.replace("Z", "+00:00"),
    ]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def parse_date(value: str | date | datetime | None) -> date | None:
    """Parse a value into a date."""

    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_money(value: str | int | float | Decimal | None) -> float | None:
    """Parse Spanish/EU-style money values into floats."""

    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return float(value)
    raw = value.strip()
    if not raw:
        return None
    cleaned = raw.replace("€", "").replace("EUR", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def normalize_status(value: str | None) -> TenderStatus:
    """Map source-specific status text into a normalized tender status."""

    folded = fold_text(value)
    if not folded:
        return TenderStatus.UNKNOWN
    if folded in {"pre"}:
        return TenderStatus.PLANNED
    if folded in {"pub"}:
        return TenderStatus.OPEN
    if folded in {"ev", "res", "des"}:
        return TenderStatus.CLOSED
    if folded in {"adj"}:
        return TenderStatus.AWARDED
    if folded in {"anul"}:
        return TenderStatus.CANCELLED
    if any(term in folded for term in ("anuncio previo", "prior information")):
        return TenderStatus.PLANNED
    if any(term in folded for term in ("anulada", "cancel", "desist", "renuncia")):
        return TenderStatus.CANCELLED
    if any(term in folded for term in ("adjudic", "awarded")):
        return TenderStatus.AWARDED
    if any(term in folded for term in ("cerrad", "closed", "finalizada", "resuelta")):
        return TenderStatus.CLOSED
    if any(term in folded for term in ("publicada", "open", "abierta", "licitacion")):
        return TenderStatus.OPEN
    return TenderStatus.UNKNOWN


def normalize_region(value: str | None) -> str | None:
    """Normalize region text while preserving a display-friendly value."""

    normalized = normalize_text(value)
    if not normalized:
        return None
    return normalized.title()
