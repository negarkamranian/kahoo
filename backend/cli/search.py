"""Search indexing, evaluation, and enrichment commands."""

import math
import statistics
import time

from backend.database import connect
from backend.models.search import (
    Enrichment,
    EnrichmentResult,
    LatencyMetrics,
    QueryEvaluation,
    ReindexResult,
    SearchBenchmark,
    SearchEvaluation,
)
from backend.search.embeddings import embed_pending_documents, embedding_enabled
from backend.search.enrichment import save_llm_enrichment
from backend.search.indexing import sync_search_index
from backend.search.ranking import ndcg_at_k
from backend.search.service import merchants


def evaluate_query(case):
    started = time.perf_counter()
    results = merchants(query=case.query)
    latency = (time.perf_counter() - started) * 1000
    ranked = [item.handle for item in results[:10]]
    grades = case.relevance
    expected = set(grades)
    first_rank = next((index for index, handle in enumerate(ranked, 1) if handle in expected), None)
    relevance = [grades.get(handle, 0) for handle in ranked]
    ndcg = ndcg_at_k(relevance, list(grades.values()), 10)
    recall = len(expected & set(ranked)) / len(expected)
    row = QueryEvaluation(
        query=case.query,
        passed_at_5=first_rank is not None and first_rank <= 5,
        first_relevant_rank=first_rank,
        recall_at_10=round(recall, 3),
        ndcg_at_10=round(ndcg, 3),
        latency_ms=round(latency, 1),
        top_10=ranked,
    )
    return row, recall, ndcg, latency


def evaluate(args):
    benchmark = SearchBenchmark.model_validate_json(args.benchmark.read_bytes())
    evaluations = [evaluate_query(case) for case in benchmark.queries]
    rows, recalls, ndcg_scores, latencies = zip(*evaluations, strict=True)
    return SearchEvaluation(
        queries=len(rows),
        success_at_5=round(sum(row.passed_at_5 for row in rows) / len(rows), 3),
        mrr_at_5=round(
            sum(1 / row.first_relevant_rank for row in rows if row.passed_at_5) / len(rows), 3
        ),
        recall_at_10=round(sum(recalls) / len(rows), 3),
        ndcg_at_10=round(sum(ndcg_scores) / len(rows), 3),
        zero_result_rate=round(sum(not row.top_10 for row in rows) / len(rows), 3),
        latency_ms=LatencyMetrics(
            p50=round(statistics.median(latencies), 1),
            p95=round(sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 1),
        ),
        results=rows,
    )


def reindex(args):
    with connect() as db:
        pending = sync_search_index(db)
    embedded = 0
    while True:
        with connect() as db:
            batch = embed_pending_documents(db, args.batch_size)
        embedded += batch
        if not args.all or batch < args.batch_size:
            break
    return ReindexResult(
        pending_documents=pending, embedded=embedded, embedding_enabled=embedding_enabled()
    )


def enrich(args):
    enrichment = Enrichment.model_validate_json(args.source.read_bytes())
    save_llm_enrichment(args.merchant_id, enrichment)
    return EnrichmentResult(merchant_id=args.merchant_id, updated=True)
