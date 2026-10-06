"""Search enrichment, retrieval, suggestions, benchmarks, and command reports."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.models.common import Count, InputModel, InstagramHandle, NonEmptyText

SearchEntityType = Literal["merchant", "post"]


SuggestionType = Literal["merchant", "category", "query", "popular"]

SEMANTIC_MATCH_THRESHOLD = 0.55
DOCUMENT_MATCH_THRESHOLD = 0.25

EnrichmentText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SearchTerm = Annotated[EnrichmentText, Field(max_length=120)]


class EnrichmentSource(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    url: AnyHttpUrl
    kind: Annotated[EnrichmentText, Field(max_length=64)]
    status: Annotated[EnrichmentText, Field(max_length=64)]
    note: str = Field(default="", max_length=1000)


class Enrichment(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    description: Annotated[EnrichmentText, Field(max_length=6000)]
    terms: list[SearchTerm] = Field(min_length=1, max_length=50)
    model: Annotated[EnrichmentText, Field(max_length=200)]
    source_url: Annotated[EnrichmentText, Field(max_length=2048)]
    confidence: float = Field(default=0.75, ge=0, le=1)
    seo_title: Annotated[EnrichmentText, Field(max_length=120)] | None = None
    meta_description: Annotated[EnrichmentText, Field(max_length=320)] | None = None
    sources: list[EnrichmentSource] = Field(default_factory=list, max_length=50)
    limitations: list[Annotated[EnrichmentText, Field(max_length=1000)]] = Field(
        default_factory=list, max_length=30
    )

    @field_validator("description", "terms")
    @classmethod
    def require_searchable_text(cls, value):
        texts = value if isinstance(value, list) else [value]
        if any(not any(character.isalnum() for character in text) for text in texts):
            raise ValueError("Description and search terms must contain letters or numbers")
        return value


class MerchantEnrichment(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    handle: InstagramHandle
    enrichment: Enrichment


class BatchEnrichment(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    researched_at: AwareDatetime
    merchants: list[MerchantEnrichment] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_handles(self):
        handles = [merchant.handle for merchant in self.merchants]
        if len(handles) != len(set(handles)):
            raise ValueError("Enrichment batch must contain unique merchant handles")
        return self


class BatchEnrichmentResult(BaseModel):
    merchants: Count
    updated: Count
    unchanged: Count
    handles: list[InstagramHandle]


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


class TextMatch(BaseModel):
    score: float = 0
    phrase_bonus: float = 0
    coverage: float = 0
    matched_tokens: int = 0
    fields: set[str] = Field(default_factory=set)
    fuzzy: bool = False


class SearchField(BaseModel):
    name: str
    text: str
    token_weight: float
    phrase_weight: float


class SearchContext(BaseModel):
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


class SearchEvidence(BaseModel):
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
