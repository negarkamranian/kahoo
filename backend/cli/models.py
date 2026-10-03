"""Validated maintenance inputs and structured command results."""

from pydantic import BaseModel

from backend.models import Count


class QueryEvaluation(BaseModel):
    query: str
    passed_at_5: bool
    first_relevant_rank: int | None
    recall_at_10: float
    ndcg_at_10: float
    latency_ms: float
    top_10: list[str]


class LatencyMetrics(BaseModel):
    p50: float
    p95: float


class SearchEvaluation(BaseModel):
    queries: Count
    success_at_5: float
    mrr_at_5: float
    recall_at_10: float
    ndcg_at_10: float
    zero_result_rate: float
    latency_ms: LatencyMetrics
    results: list[QueryEvaluation]


class ReindexResult(BaseModel):
    pending_documents: Count
    embedded: Count
    embedding_enabled: bool


class EnrichmentResult(BaseModel):
    merchant_id: int
    updated: bool


class CategoryBuildResult(BaseModel):
    categories: Count
    excluded_branches: Count
    output: str
