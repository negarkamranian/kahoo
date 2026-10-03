"""Analytics events and administrative dashboard metrics."""

from datetime import datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field

from backend.models.common import Count, InputModel
from backend.models.merchants import MerchantSummary


class AnalyticsEvent(InputModel):
    event_type: Literal[
        "search",
        "category_view",
        "merchant_click",
        "login_started",
        "login_completed",
        "oauth_started",
        "oauth_completed",
    ]
    session_id: str = Field(min_length=8, max_length=80)
    query: str
    category_code: str
    merchant_id: Count
    result_count: Count


class MetricsPeriod(IntEnum):
    WEEK = 7
    MONTH = 30
    QUARTER = 90


class MetricsKpis(BaseModel):
    searches: Count
    visitors: Count
    clicks: Count
    zero_rate: float
    search_to_click: float


class CatalogMetrics(BaseModel):
    merchants: Count
    used_categories: Count
    posts: Count
    avatars: Count
    descriptions: Count


class DailyMetrics(BaseModel):
    date: str
    searches: Count
    clicks: Count
    visitors: Count
    zero_results: Count


class QueryMetrics(BaseModel):
    query: str
    searches: Count


class TopQueryMetrics(QueryMetrics):
    avg_results: float | None
    zero_results: Count


class MerchantClickMetrics(MerchantSummary):
    clicks: Count


class CategoryViewMetrics(BaseModel):
    label: str
    views: Count


class FunnelMetrics(BaseModel):
    visitors: Count
    searched: Count
    clicked: Count
    oauth_started: Count
    oauth_completed: Count


class AdminMetrics(BaseModel):
    period_days: MetricsPeriod
    generated_at: datetime
    kpis: MetricsKpis
    catalog: CatalogMetrics
    daily: list[DailyMetrics]
    top_queries: list[TopQueryMetrics]
    missed_queries: list[QueryMetrics]
    top_merchants: list[MerchantClickMetrics]
    top_categories: list[CategoryViewMetrics]
    funnel: FunnelMetrics
