#!/usr/bin/env python3
"""Run Kahoo's reviewed offline search relevance benchmark."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import run_migrations
from backend.server import merchants


def main():
    benchmark = json.loads(
        (PROJECT_ROOT / "data" / "search_benchmarks.json").read_text(encoding="utf-8")
    )
    run_migrations()
    reciprocal_ranks = []
    rows = []
    for case in benchmark["queries"]:
        results = merchants(query=case["query"])
        ranked = [item["handle"] for item in results[:5]]
        expected = set(case["expected_handles"])
        first_rank = next((index for index, handle in enumerate(ranked, 1) if handle in expected), None)
        reciprocal_ranks.append(1 / first_rank if first_rank else 0)
        rows.append({
            "query": case["query"],
            "passed_at_5": first_rank is not None,
            "first_relevant_rank": first_rank,
            "top_5": ranked,
        })
    report = {
        "queries": len(rows),
        "success_at_5": round(sum(row["passed_at_5"] for row in rows) / len(rows), 3),
        "mrr_at_5": round(sum(reciprocal_ranks) / len(rows), 3),
        "results": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
