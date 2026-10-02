#!/usr/bin/env python3
"""Run Kahoo's reviewed offline search relevance benchmark."""

import json
import math
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import run_migrations
from backend.search import ndcg_at_k
from backend.server import merchants


def main():
    benchmark = json.loads(
        (PROJECT_ROOT / "data" / "search_benchmarks.json").read_text(encoding="utf-8")
    )
    run_migrations()
    reciprocal_ranks = []
    ndcg_scores = []
    recalls = []
    latencies = []
    rows = []
    for case in benchmark["queries"]:
        started=time.perf_counter();results=merchants(query=case["query"])
        latencies.append((time.perf_counter()-started)*1000)
        ranked = [item["handle"] for item in results[:10]]
        grades=case.get("relevance") or {handle:1 for handle in case["expected_handles"]}
        expected=set(grades)
        first_rank = next((index for index, handle in enumerate(ranked, 1) if handle in expected), None)
        reciprocal_ranks.append(1 / first_rank if first_rank and first_rank<=5 else 0)
        relevance=[grades.get(handle,0) for handle in ranked]
        ndcg_scores.append(ndcg_at_k(relevance,list(grades.values()),10))
        recalls.append(len(expected & set(ranked))/len(expected) if expected else 0)
        rows.append({
            "query": case["query"],
            "passed_at_5": first_rank is not None and first_rank<=5,
            "first_relevant_rank": first_rank,
            "recall_at_10":round(recalls[-1],3),
            "ndcg_at_10":round(ndcg_scores[-1],3),
            "latency_ms":round(latencies[-1],1),
            "top_10": ranked,
        })
    report = {
        "queries": len(rows),
        "success_at_5": round(sum(row["passed_at_5"] for row in rows) / len(rows), 3),
        "mrr_at_5": round(sum(reciprocal_ranks) / len(rows), 3),
        "recall_at_10":round(sum(recalls)/len(rows),3),
        "ndcg_at_10":round(sum(ndcg_scores)/len(rows),3),
        "zero_result_rate":round(sum(not row["top_10"] for row in rows)/len(rows),3),
        "latency_ms":{"p50":round(statistics.median(latencies),1),
          "p95":round(sorted(latencies)[max(0,math.ceil(len(latencies)*.95)-1)],1)},
        "results": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
