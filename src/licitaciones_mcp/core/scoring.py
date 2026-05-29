"""Tender scoring and filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from math import sqrt
from typing import Any

from licitaciones_mcp.core.models import Tender, TenderFilters, TenderSearchResult, TenderStatus
from licitaciones_mcp.core.normalization import (
    fold_text,
    normalize_cpv_codes,
    normalize_cpv_prefixes,
)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two vectors."""

    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def tender_matches_filters(tender: Tender, filters: TenderFilters) -> bool:
    """Return whether a tender satisfies hard structured filters."""

    if filters.only_open and tender.status != TenderStatus.OPEN:
        return False
    if filters.statuses and tender.status not in filters.statuses:
        return False
    if filters.sources and tender.source not in filters.sources:
        return False
    if filters.country and tender.country.upper() != filters.country:
        return False

    wanted_cpvs = normalize_cpv_codes(filters.cpv_codes)
    if wanted_cpvs and not _cpv_overlaps(tender.cpv_codes, wanted_cpvs):
        return False

    wanted_cpv_prefixes = normalize_cpv_prefixes(filters.cpv_prefixes)
    if wanted_cpv_prefixes and not _cpv_prefix_overlaps(tender.cpv_codes, wanted_cpv_prefixes):
        return False

    wanted_nuts = [fold_text(code) for code in filters.nuts_codes]
    if wanted_nuts:
        tender_nuts = [fold_text(code) for code in tender.nuts_codes]
        if not any(code.startswith(wanted) for code in tender_nuts for wanted in wanted_nuts):
            return False

    if filters.regions:
        tender_region = fold_text(tender.region)
        wanted_regions = [fold_text(region) for region in filters.regions]
        if not any(region in tender_region or tender_region in region for region in wanted_regions):
            return False

    buyer_filters = list(filters.buyer_names)
    if filters.buyer:
        buyer_filters.append(filters.buyer)
    if buyer_filters:
        buyer = fold_text(tender.buyer_name)
        if not any(fold_text(name) in buyer for name in buyer_filters):
            return False

    if filters.procedure_types and not _text_field_matches(
        tender.procedure_type, filters.procedure_types
    ):
        return False
    if filters.contract_types and not _text_field_matches(
        tender.contract_type, filters.contract_types
    ):
        return False
    if filters.notice_types and not _text_field_matches(tender.notice_type, filters.notice_types):
        return False
    if filters.dataset_kinds:
        dataset_kind = fold_text(str(tender.source_metadata.get("dataset_kind", "")))
        wanted_dataset_kinds = [fold_text(kind) for kind in filters.dataset_kinds]
        if not dataset_kind or dataset_kind not in wanted_dataset_kinds:
            return False

    if filters.published_from and (
        tender.published_at is None or tender.published_at.date() < filters.published_from
    ):
        return False
    if filters.published_to and (
        tender.published_at is None or tender.published_at.date() > filters.published_to
    ):
        return False
    if filters.deadline_from and (
        tender.deadline_at is None or tender.deadline_at.date() < filters.deadline_from
    ):
        return False
    if filters.deadline_to and (
        tender.deadline_at is None or tender.deadline_at.date() > filters.deadline_to
    ):
        return False

    if filters.min_value is not None and (
        tender.estimated_value is None or tender.estimated_value < filters.min_value
    ):
        return False
    return not (
        filters.max_value is not None
        and (tender.estimated_value is None or tender.estimated_value > filters.max_value)
    )


def score_tender(
    tender: Tender,
    filters: TenderFilters,
    *,
    semantic_score: float | None = None,
) -> TenderSearchResult:
    """Score a tender against structured filters and optional semantic score."""

    score = 0.0
    reasons: list[str] = []

    text_score = _keyword_score(tender, filters.text)
    if text_score:
        score += text_score * 40
        reasons.append("text_match")

    wanted_cpvs = normalize_cpv_codes(filters.cpv_codes)
    if wanted_cpvs:
        cpv_score = _cpv_score(tender.cpv_codes, wanted_cpvs)
        if cpv_score:
            score += cpv_score * 35
            reasons.append("cpv_match")

    wanted_cpv_prefixes = normalize_cpv_prefixes(filters.cpv_prefixes)
    if wanted_cpv_prefixes and _cpv_prefix_overlaps(tender.cpv_codes, wanted_cpv_prefixes):
        score += 18
        reasons.append("cpv_prefix_match")

    if filters.regions and tender.region:
        score += 10
        reasons.append("region_match")

    if filters.buyer and tender.buyer_name:
        score += 8
        reasons.append("buyer_match")

    if tender.status == TenderStatus.OPEN:
        score += 8
        reasons.append("open")

    if tender.deadline_at:
        days_left = (tender.deadline_at - datetime.now(UTC)).days
        if days_left >= 0:
            urgency = max(0, 7 - min(days_left, 7))
            score += urgency
            reasons.append("deadline_active")

    if semantic_score is not None:
        score += max(0.0, min(semantic_score, 1.0)) * 25
        reasons.append("semantic_match")

    return TenderSearchResult(tender=tender, score=round(score, 4), reasons=reasons)


def rank_tenders(
    tenders: list[Tender],
    filters: TenderFilters,
    *,
    semantic_scores: dict[str, float] | None = None,
) -> list[TenderSearchResult]:
    """Filter and rank tenders using deterministic scoring."""

    scores = semantic_scores or {}
    results = [
        score_tender(tender, filters, semantic_score=scores.get(tender.source_id))
        for tender in tenders
        if tender_matches_filters(tender, filters)
    ]
    ordered = _sort_results(results, filters)
    return ordered[filters.offset : filters.offset + filters.limit]


def _keyword_score(tender: Tender, text: str | None) -> float:
    if not text:
        return 0.0
    searchable = fold_text(tender.searchable_text)
    terms = [term for term in fold_text(text).split() if len(term) > 2]
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in searchable)
    return hits / len(terms)


def _cpv_overlaps(tender_cpvs: list[str], wanted_cpvs: list[str]) -> bool:
    return _cpv_score(tender_cpvs, wanted_cpvs) > 0


def _cpv_prefix_overlaps(tender_cpvs: list[str], wanted_prefixes: list[str]) -> bool:
    return any(
        tender_cpv.startswith(prefix) for tender_cpv in tender_cpvs for prefix in wanted_prefixes
    )


def _cpv_score(tender_cpvs: list[str], wanted_cpvs: list[str]) -> float:
    if not tender_cpvs or not wanted_cpvs:
        return 0.0
    best = 0.0
    for tender_cpv in tender_cpvs:
        for wanted_cpv in wanted_cpvs:
            if tender_cpv == wanted_cpv:
                best = max(best, 1.0)
            elif tender_cpv[:5] == wanted_cpv[:5]:
                best = max(best, 0.75)
            elif tender_cpv[:3] == wanted_cpv[:3]:
                best = max(best, 0.5)
            elif tender_cpv[:2] == wanted_cpv[:2]:
                best = max(best, 0.25)
    return best


def _text_field_matches(value: str | None, filters: list[str]) -> bool:
    folded_value = fold_text(value)
    return bool(folded_value) and any(fold_text(item) in folded_value for item in filters)


def _sort_results(
    results: list[TenderSearchResult], filters: TenderFilters
) -> list[TenderSearchResult]:
    reverse = filters.order == "desc"
    if filters.order_by == "score":
        return sorted(results, key=lambda item: item.score, reverse=reverse)

    def key(item: TenderSearchResult) -> Any:
        value = getattr(item.tender, filters.order_by)
        if value is None:
            return datetime.min.replace(tzinfo=UTC) if filters.order_by.endswith("_at") else -1.0
        return value

    return sorted(results, key=key, reverse=reverse)
