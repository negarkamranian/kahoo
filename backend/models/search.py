"""Search enrichment, retrieval, suggestions, benchmarks, and command reports."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.common import Count, InputModel, InstagramHandle, NonEmptyText

SearchEntityType = Literal["merchant", "post"]


SuggestionType = Literal["merchant", "category", "query", "popular"]

SEMANTIC_MATCH_THRESHOLD = 0.55
DOCUMENT_MATCH_THRESHOLD = 0.25


class Enrichment(InputModel):
    description: str
    terms: list[str]
    model: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    confidence: float = Field(default=0.75, ge=0, le=1)


class SearchSuggestion(BaseModel):
    value: str
    label: str
    type: SuggestionType


class BenchmarkQuery(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: NonEmptyText
    relevance: dict[InstagramHandle, Annotated[int, Field(strict=True, ge=1, le=3)]] = Field(
        min_length=1
    )


class SearchBenchmark(InputModel):
    queries: list[BenchmarkQuery] = Field(min_length=1)


class LexicalMatch(BaseModel):
    score: float
    entity_type: SearchEntityType
    entity_id: int
    published_at: datetime | None = None


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


class EnrichmentResult(BaseModel):
    merchant_id: int
    updated: bool


@dataclass
class TextMatch:
    score: float = 0
    phrase_bonus: float = 0
    coverage: float = 0
    matched_tokens: int = 0
    fields: set[str] = field(default_factory=set)
    fuzzy: bool = False


@dataclass
class SearchField:
    name: str
    text: str
    token_weight: float
    phrase_weight: float


@dataclass
class SearchContext:
    phrase: str
    tokens: list[str]
    categories: dict
    assignments: dict
    terms: dict
    lexical: dict[int, LexicalMatch]
    semantic: dict[int, float]
    fused: dict[int, float]
    clicks: dict[int, int]
    query_clicks: dict[int, int]


@dataclass
class SearchEvidence:
    text: TextMatch
    lexical: LexicalMatch | None
    semantic: float

    @property
    def has_post(self):
        return self.lexical is not None and self.lexical.entity_type == "post"

    @property
    def has_semantic_match(self):
        return self.semantic >= SEMANTIC_MATCH_THRESHOLD

    @property
    def has_document_match(self):
        return self.lexical is not None and self.lexical.score >= DOCUMENT_MATCH_THRESHOLD
