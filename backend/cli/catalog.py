from urllib.request import Request, urlopen

from backend.models.categories import CategoryBuildResult, CategoryPolicy, GpcPublication
from backend.search.normalization import normalize_persian
from backend.services.catalog import import_catalog

API = "https://gpc-api.gs1.org/api/browser/download/publication/{}/json"
HEADERS = {
    "Origin": "https://gpc-browser.gs1.org",
    "Referer": "https://gpc-browser.gs1.org/",
    "Content-Type": "application/json;charset=utf-8",
    "User-Agent": "Mozilla/5.0",
}


def download(publication_id, path):
    with urlopen(Request(API.format(publication_id), headers=HEADERS), timeout=120) as response:
        path.write_bytes(response.read())


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.children)


def sql(value):
    return "'" + str(value).replace("'", "''") + "'"


def keep_category(node, segment, path, policy, excluded):
    code = str(node.code)
    title = node.title
    full_path = " / ".join((*path, title)).lower()
    terms = [term.lower() for term in policy.excluded_terms]
    terms.extend(term.lower() for term in policy.segment_excluded_terms.get(segment, []))
    matched = next((term for term in terms if term in full_path), None)
    if matched:
        excluded.append((code, title, matched))
        return None
    children = [
        child
        for raw in node.children
        if raw.active and raw.level <= 4
        if (child := keep_category(raw, segment, (*path, title), policy, excluded))
    ]
    if node.level < 4 and not children:
        return None
    return node, children


def flatten_categories(item, labels, parent=None, order=0):
    node, children = item
    code = str(node.code)
    if code not in labels:
        raise ValueError(f"Missing Persian category label for {code}: {node.title}")
    label = labels[code]
    yield code, parent, node.level, label, node.title, order
    for index, child in enumerate(children, 1):
        yield from flatten_categories(child, labels, code, index * 10)


def category_rows(current, labels, policy):
    rows, excluded = [], []
    allowed = set(policy.allowed_segments)
    for order, node in enumerate(current.nodes, 1):
        code = str(node.code)
        if code in allowed and node.active:
            item = keep_category(node, code, (), policy, excluded)
            if item:
                rows.extend(flatten_categories(item, labels, order=order * 10))
    return rows, excluded


def category_seed_rows(rows, policy):
    lines = [
        f"-- Generated from {policy.source}; do not edit manually.",
        "BEGIN;",
        "CREATE TEMP TABLE _category_seed(code TEXT PRIMARY KEY,parent_code TEXT,level INTEGER,label_fa TEXT,label_en TEXT,sort_order INTEGER);",
    ]
    for row in rows:
        values = ",".join("NULL" if value is None else sql(value) for value in row)
        lines.append(f"INSERT INTO _category_seed VALUES({values});")
    return lines


def category_upserts():
    lines = []
    for level in range(1, 5):
        lines.append(
            "INSERT INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) "
            "SELECT code,parent_code,level,label_fa,label_en,NULL,sort_order FROM _category_seed "
            f"WHERE level={level} ON CONFLICT(code) DO UPDATE SET "
            "parent_code=excluded.parent_code,level=excluded.level,label_fa=excluded.label_fa,"
            "label_en=excluded.label_en,icon=NULL,sort_order=excluded.sort_order;"
        )
    return lines


def category_deletions():
    lines = []
    for level in range(4, 0, -1):
        lines.append(
            f"DELETE FROM categories WHERE level={level} "
            "AND code NOT IN (SELECT code FROM _category_seed) "
            "AND code NOT IN (SELECT category_code FROM merchants) "
            "AND code NOT IN (SELECT category_code FROM merchant_categories) "
            "AND code NOT IN (SELECT category_code FROM analytics_events WHERE category_code IS NOT NULL) "
            "AND code NOT IN (SELECT parent_code FROM categories WHERE parent_code IS NOT NULL);"
        )
    return lines


def category_seed_metadata(policy, category_count, excluded_count):
    lines = []
    lines.extend(
        [
            f"INSERT INTO category_metadata(key,value) VALUES('gpc_source',{sql(policy.source)}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
            f"INSERT INTO category_metadata(key,value) VALUES('category_count',{sql(category_count)}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
            f"INSERT INTO category_metadata(key,value) VALUES('excluded_branch_count',{sql(excluded_count)}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
            "DROP TABLE _category_seed;",
            "COMMIT;",
            "",
        ]
    )
    return lines


def build(args):
    policy = CategoryPolicy.model_validate_json(args.policy.read_bytes())
    if args.download:
        download(policy.source_publication_id, args.current)
        download(policy.persian_publication_id, args.persian)
    current = GpcPublication.model_validate_json(args.current.read_bytes())
    persian = GpcPublication.model_validate_json(args.persian.read_bytes())
    labels = {
        str(node.code): normalize_persian(node.title) for node in walk(persian.nodes) if node.active
    }
    labels.update(policy.segment_labels_fa)
    rows, excluded = category_rows(current, labels, policy)
    lines = [
        *category_seed_rows(rows, policy),
        *category_upserts(),
        *category_deletions(),
        *category_seed_metadata(policy, len(rows), len(excluded)),
    ]
    args.output.write_text("\n".join(lines))
    return CategoryBuildResult(
        categories=len(rows), excluded_branches=len(excluded), output=str(args.output)
    )


def import_snapshots(args):
    return import_catalog(args.paths)
