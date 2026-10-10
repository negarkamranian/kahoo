"""Rerank a bounded candidate set with a multilingual TEI cross-encoder."""

import json
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from backend.config import settings

MAX_CANDIDATES = 40


class RerankScore(BaseModel):
    index: int = Field(ge=0)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


def candidate_text(merchant, terms):
    captions = " ".join(post.caption for post in merchant.posts if post.caption)
    return "\n".join(
        [
            merchant.name,
            merchant.handle,
            merchant.city,
            merchant.category_label or "",
            merchant.description,
            merchant.biography,
            " ".join(term for term, _ in terms),
            captions,
        ]
    )


def rerank_merchants(query, merchants, terms_by_merchant=None):
    if not settings.rerank_api_url or not merchants:
        return merchants
    candidates = merchants[:MAX_CANDIDATES]
    terms_by_merchant = terms_by_merchant or {}
    payload = json.dumps(
        {
            "query": query,
            "texts": [
                candidate_text(item, terms_by_merchant.get(item.id, [])) for item in candidates
            ],
            "raw_scores": False,
        }
    ).encode("utf-8")
    request = Request(
        settings.rerank_api_url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urlopen(request, timeout=60) as response:
        scores = [RerankScore.model_validate(item) for item in json.load(response)]
    if sorted(item.index for item in scores) != list(range(len(candidates))):
        raise ValueError("Reranker must return one score for every candidate")
    results = []
    for item in scores:
        merchant = candidates[item.index]
        if item.score < settings.rerank_min_score:
            continue
        merchant.search_score = round(item.score * 100, 4)
        results.append(merchant)
    return sorted(results, key=lambda item: (item.search_score, item.match_coverage), reverse=True)
