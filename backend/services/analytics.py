from datetime import datetime, timedelta

from backend.database import connect
from backend.models.analytics import (
    AdminMetrics,
    AnalyticsEvent,
    CatalogMetrics,
    CategoryViewMetrics,
    DailyMetrics,
    FunnelMetrics,
    MerchantClickMetrics,
    MetricsKpis,
    MetricsPeriod,
    QueryMetrics,
    TopQueryMetrics,
)


def record_event(event: AnalyticsEvent) -> bool:
    with connect() as db:
        db.execute(
            "INSERT INTO analytics_events(event_type,session_id,query,category_code,merchant_id,result_count) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                event.event_type,
                event.session_id,
                event.query,
                event.category_code or None,
                event.merchant_id or None,
                event.result_count,
            ),
        )
    return True


def event_count(db, since, condition, distinct_sessions=False):
    counted = "DISTINCT session_id" if distinct_sessions else "*"
    return db.execute(
        f"SELECT COUNT({counted}) FROM analytics_events WHERE created_at>=%s AND {condition}",
        (since,),
    ).fetchone()["count"]


def percent(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else 0


def funnel_metrics(db, since):
    return FunnelMetrics(
        visitors=event_count(db, since, "TRUE", distinct_sessions=True),
        searched=event_count(db, since, "event_type='search'", distinct_sessions=True),
        clicked=event_count(db, since, "event_type='merchant_click'", distinct_sessions=True),
        oauth_started=event_count(db, since, "event_type='oauth_started'"),
        oauth_completed=event_count(db, since, "event_type='oauth_completed'"),
    )


def kpi_metrics(db, since, funnel):
    searches = event_count(db, since, "event_type='search'")
    zero_searches = event_count(db, since, "event_type='search' AND result_count=0")
    return MetricsKpis(
        searches=searches,
        visitors=funnel.visitors,
        clicks=event_count(db, since, "event_type='merchant_click'"),
        zero_rate=percent(zero_searches, searches),
        search_to_click=percent(funnel.clicked, funnel.searched),
    )


def daily_metrics(db, since, date_keys):
    daily_rows = {
        row["event_day"]: DailyMetrics(date=row["event_day"], **row)
        for row in db.execute(
            """
      SELECT to_char(created_at,'YYYY-MM-DD') AS event_day,
        COUNT(*) FILTER (WHERE event_type='search') searches,
        COUNT(*) FILTER (WHERE event_type='merchant_click') clicks,
        COUNT(DISTINCT session_id) visitors,
        COUNT(*) FILTER (WHERE event_type='search' AND result_count=0) zero_results
      FROM analytics_events WHERE created_at>=%s GROUP BY 1 ORDER BY 1
    """,
            (since,),
        )
    }
    daily = [
        daily_rows.get(day)
        or DailyMetrics(date=day, searches=0, clicks=0, visitors=0, zero_results=0)
        for day in date_keys
    ]
    return daily


def top_query_metrics(db, since):
    top_queries = [
        TopQueryMetrics.model_validate(row)
        for row in db.execute(
            """
      SELECT query,COUNT(*) searches,ROUND(AVG(result_count),1)::double precision avg_results,
        COUNT(*) FILTER (WHERE result_count=0) zero_results
      FROM analytics_events WHERE created_at>=%s AND event_type='search' AND query IS NOT NULL
      GROUP BY query ORDER BY searches DESC LIMIT 10
    """,
            (since,),
        )
    ]
    return top_queries


def missed_query_metrics(db, since):
    missed_queries = [
        QueryMetrics.model_validate(row)
        for row in db.execute(
            """
      SELECT query,COUNT(*) searches FROM analytics_events
      WHERE created_at>=%s AND event_type='search' AND result_count=0 AND query IS NOT NULL
      GROUP BY query ORDER BY searches DESC LIMIT 8
    """,
            (since,),
        )
    ]
    return missed_queries


def merchant_click_metrics(db, since):
    top_merchants = [
        MerchantClickMetrics.model_validate(row)
        for row in db.execute(
            """
      SELECT m.id,m.name,m.handle,COUNT(e.id) clicks FROM analytics_events e
      JOIN merchants m ON m.id=e.merchant_id
      WHERE e.created_at>=%s AND e.event_type='merchant_click'
      GROUP BY m.id ORDER BY clicks DESC,m.id DESC LIMIT 8
    """,
            (since,),
        )
    ]
    return top_merchants


def category_view_metrics(db, since):
    top_categories = [
        CategoryViewMetrics.model_validate(row)
        for row in db.execute(
            """
      SELECT c.label_fa label,COUNT(e.id) views FROM analytics_events e
      JOIN categories c ON c.code=e.category_code
      WHERE e.created_at>=%s AND e.event_type='category_view'
      GROUP BY c.code ORDER BY views DESC LIMIT 8
    """,
            (since,),
        )
    ]
    return top_categories


def catalog_metrics(db):
    catalog = CatalogMetrics.model_validate(
        db.execute("""
      SELECT (SELECT COUNT(*) FROM merchants) merchants,
        (SELECT COUNT(DISTINCT category_code) FROM merchants) used_categories,
        (SELECT COUNT(*) FROM merchant_posts) posts,
        (SELECT COUNT(*) FROM merchants WHERE avatar_blob IS NOT NULL) avatars,
        (SELECT COUNT(*) FROM merchants WHERE description!='') descriptions
    """).fetchone()
    )
    return catalog


def admin_metrics(period: MetricsPeriod = MetricsPeriod.MONTH) -> AdminMetrics:
    now = datetime.now().replace(microsecond=0)
    since = (now - timedelta(days=period.value - 1)).strftime("%Y-%m-%d 00:00:00")
    dates = [
        (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(period.value - 1, -1, -1)
    ]
    with connect() as db:
        funnel = funnel_metrics(db, since)
        return AdminMetrics(
            period_days=period,
            generated_at=now,
            kpis=kpi_metrics(db, since, funnel),
            catalog=catalog_metrics(db),
            daily=daily_metrics(db, since, dates),
            top_queries=top_query_metrics(db, since),
            missed_queries=missed_query_metrics(db, since),
            top_merchants=merchant_click_metrics(db, since),
            top_categories=category_view_metrics(db, since),
            funnel=funnel,
        )
