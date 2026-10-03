import re
from datetime import datetime, timedelta

from backend.database import connect

ANALYTICS_EVENTS = {
    "search",
    "category_view",
    "merchant_click",
    "login_started",
    "login_completed",
    "oauth_started",
    "oauth_completed",
}


def record_event(
    event_type, session_id, query=None, category_code=None, merchant_id=None, result_count=None
):
    if event_type not in ANALYTICS_EVENTS:
        return False
    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(session_id or ""))[:80]
    if len(session_id) < 8:
        return False
    query = (query or "").strip()[:160] or None
    try:
        merchant_id = int(merchant_id) if merchant_id is not None else None
        result_count = int(result_count) if result_count is not None else None
    except (TypeError, ValueError):
        return False
    with connect() as db:
        db.execute(
            "INSERT INTO analytics_events(event_type,session_id,query,category_code,merchant_id,result_count) VALUES(%s,%s,%s,%s,%s,%s)",
            (event_type, session_id, query, category_code or None, merchant_id, result_count),
        )
    return True


def admin_metrics(days=30):
    days = days if days in (7, 30, 90) else 30
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    date_keys = [
        (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(days - 1, -1, -1)
    ]
    with connect() as db:

        def count(condition):
            return db.execute(
                f"SELECT COUNT(*) FROM analytics_events WHERE created_at>=%s AND {condition}",
                (since,),
            ).fetchone()["count"]

        searches = count("event_type='search'")
        clicks = count("event_type='merchant_click'")
        zero_searches = count("event_type='search' AND result_count=0")
        visitors = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s", (since,)
        ).fetchone()["count"]
        searched_sessions = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s AND event_type='search'",
            (since,),
        ).fetchone()["count"]
        clicked_sessions = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s AND event_type='merchant_click'",
            (since,),
        ).fetchone()["count"]
        daily_rows = {
            row["event_day"]: dict(row)
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
            {"date": day, "searches": 0, "clicks": 0, "visitors": 0, "zero_results": 0}
            | daily_rows.get(day, {})
            for day in date_keys
        ]
        top_queries = [
            dict(row)
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
        missed_queries = [
            dict(row)
            for row in db.execute(
                """
          SELECT query,COUNT(*) searches FROM analytics_events
          WHERE created_at>=%s AND event_type='search' AND result_count=0 AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC LIMIT 8
        """,
                (since,),
            )
        ]
        top_merchants = [
            dict(row)
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
        top_categories = [
            dict(row)
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
        catalog = dict(
            db.execute("""
          SELECT (SELECT COUNT(*) FROM merchants) merchants,
            (SELECT COUNT(DISTINCT category_code) FROM merchants) used_categories,
            (SELECT COUNT(*) FROM merchant_posts) posts,
            (SELECT COUNT(*) FROM merchants WHERE avatar_blob IS NOT NULL) avatars,
            (SELECT COUNT(*) FROM merchants WHERE description!='') descriptions
        """).fetchone()
        )
        oauth_started = count("event_type='oauth_started'")
        oauth_completed = count("event_type='oauth_completed'")
    return {
        "period_days": days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpis": {
            "searches": searches,
            "visitors": visitors,
            "clicks": clicks,
            "zero_rate": round(zero_searches / searches * 100, 1) if searches else 0,
            "search_to_click": round(clicked_sessions / searched_sessions * 100, 1)
            if searched_sessions
            else 0,
        },
        "catalog": catalog,
        "daily": daily,
        "top_queries": top_queries,
        "missed_queries": missed_queries,
        "top_merchants": top_merchants,
        "top_categories": top_categories,
        "funnel": {
            "visitors": visitors,
            "searched": searched_sessions,
            "clicked": clicked_sessions,
            "oauth_started": oauth_started,
            "oauth_completed": oauth_completed,
        },
    }
