from backend.database import connect
from backend.models.categories import CategoryNode


def category_counts(db, rows):
    counts = {row["code"]: 0 for row in rows}
    parents = {row["code"]: row["parent_code"] for row in rows}
    assignments = {}
    for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
        assignments.setdefault(item["merchant_id"], []).append(item["category_code"])
    for category_codes in assignments.values():
        visible = set()
        for category_code in category_codes:
            code = category_code
            while code:
                visible.add(code)
                code = parents.get(code)
        for code in visible:
            counts[code] = counts.get(code, 0) + 1
    return counts


def category_tree() -> list[CategoryNode]:
    with connect() as db:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT code,parent_code,level,label_fa,label_en,icon FROM categories ORDER BY level,sort_order,label_fa"
            )
        ]
        counts = category_counts(db, rows)
        nodes = {
            row["code"]: CategoryNode(**row, count=counts[row["code"]], children=[]) for row in rows
        }
        roots = []
        for row in rows:
            node = nodes[row["code"]]
            if row["parent_code"]:
                nodes[row["parent_code"]].children.append(node)
            else:
                roots.append(node)
        return roots
