"""Tender data quality validators."""

from __future__ import annotations

import re

from licitaciones_mcp.core.catalogs import (
    PLACSP_CONTRACT_TYPES,
    PLACSP_NOTICE_TYPES,
    PLACSP_PROCEDURE_TYPES,
)
from licitaciones_mcp.core.models import (
    Tender,
    TenderQualityIssue,
    TenderQualitySeverity,
    TenderSource,
    TenderStatus,
)
from licitaciones_mcp.core.normalization import normalize_text

CPV_CODE_RE = re.compile(r"^\d{8}$")
NUTS_CODE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{1,3}$")
SPANISH_TAX_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9]{7}[A-Z0-9]$")


def is_valid_cpv_code(value: str) -> bool:
    """Return whether a value looks like an 8-digit CPV code."""

    return bool(CPV_CODE_RE.fullmatch(value))


def is_valid_nuts_code(value: str) -> bool:
    """Return whether a value looks like a NUTS code."""

    return bool(NUTS_CODE_RE.fullmatch(value.upper()))


def normalize_tax_id(value: str | None) -> str | None:
    """Normalize a Spanish tax identifier for validation and matching."""

    if not value:
        return None
    normalized = "".join(char for char in value.upper() if char.isalnum())
    return normalized or None


def is_valid_spanish_tax_id(value: str | None) -> bool:
    """Return whether a Spanish tax ID has a plausible public shape."""

    normalized = normalize_tax_id(value)
    if normalized is None:
        return False
    return bool(SPANISH_TAX_ID_RE.fullmatch(normalized))


def validate_tender(tender: Tender) -> list[TenderQualityIssue]:
    """Return deterministic quality issues for a normalized tender."""

    issues: list[TenderQualityIssue] = []
    if not tender.cpv_codes:
        issues.append(
            TenderQualityIssue(
                code="missing_cpv",
                message="Tender has no CPV codes.",
                field="cpv_codes",
            )
        )
    for cpv in tender.cpv_codes:
        if not is_valid_cpv_code(cpv):
            issues.append(
                TenderQualityIssue(
                    code="invalid_cpv",
                    severity=TenderQualitySeverity.ERROR,
                    message=f"Invalid CPV code: {cpv}.",
                    field="cpv_codes",
                )
            )

    for nuts in tender.nuts_codes:
        if not is_valid_nuts_code(nuts):
            issues.append(
                TenderQualityIssue(
                    code="invalid_nuts",
                    message=f"Invalid NUTS code: {nuts}.",
                    field="nuts_codes",
                )
            )

    if tender.buyer_tax_id and not is_valid_spanish_tax_id(tender.buyer_tax_id):
        issues.append(
            TenderQualityIssue(
                code="invalid_buyer_tax_id",
                message=f"Invalid buyer tax identifier: {tender.buyer_tax_id}.",
                field="buyer_tax_id",
            )
        )

    if tender.estimated_value is not None and tender.estimated_value < 0:
        issues.append(
            TenderQualityIssue(
                code="negative_estimated_value",
                severity=TenderQualitySeverity.ERROR,
                message="Estimated value cannot be negative.",
                field="estimated_value",
            )
        )
    if tender.estimated_value is not None and tender.estimated_value > 50_000_000:
        issues.append(
            TenderQualityIssue(
                code="estimated_value_outlier",
                message="Estimated value is unusually high.",
                field="estimated_value",
            )
        )

    if (
        tender.published_at is not None
        and tender.deadline_at is not None
        and tender.deadline_at < tender.published_at
    ):
        issues.append(
            TenderQualityIssue(
                code="deadline_before_publication",
                message="Deadline is earlier than publication date.",
                field="deadline_at",
            )
        )
    if tender.status == TenderStatus.OPEN and tender.deadline_at is None:
        issues.append(
            TenderQualityIssue(
                code="open_without_deadline",
                message="Open tender has no submission deadline.",
                field="deadline_at",
            )
        )

    if (
        tender.estimated_value is not None
        and tender.award_value is not None
        and tender.award_value > tender.estimated_value * 1.25
    ):
        issues.append(
            TenderQualityIssue(
                code="award_exceeds_estimate",
                message="Award value is materially higher than estimated value.",
                field="award_value",
            )
        )

    if not tender.buyer_name:
        issues.append(
            TenderQualityIssue(
                code="missing_buyer",
                message="Tender has no buyer name.",
                field="buyer_name",
            )
        )

    if tender.source == TenderSource.PLACSP:
        _append_unknown_catalog_issue(
            issues,
            value=tender.notice_type,
            catalog=PLACSP_NOTICE_TYPES,
            code="unknown_notice_type",
            field="notice_type",
        )
        _append_unknown_catalog_issue(
            issues,
            value=tender.contract_type,
            catalog=PLACSP_CONTRACT_TYPES,
            code="unknown_contract_type",
            field="contract_type",
        )
        _append_unknown_catalog_issue(
            issues,
            value=tender.procedure_type,
            catalog=PLACSP_PROCEDURE_TYPES,
            code="unknown_procedure_type",
            field="procedure_type",
        )

    return issues


def _append_unknown_catalog_issue(
    issues: list[TenderQualityIssue],
    *,
    value: str | None,
    catalog: dict[str, str],
    code: str,
    field: str,
) -> None:
    normalized = (normalize_text(value) or "").upper()
    if normalized and normalized not in catalog:
        issues.append(
            TenderQualityIssue(
                code=code,
                message=f"Unknown source code for {field}: {value}.",
                field=field,
            )
        )
