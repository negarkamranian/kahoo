"""Import the pinned Shopify release, preserving the original and a compact local index."""

import gzip
import hashlib
import json
from urllib.request import Request, urlopen

from backend.models.taxonomy import ProductCategory, ProductTaxonomy, TaxonomyMetadata
from backend.services.taxonomy import TaxonomyStore, product_taxonomy

VERSION = "2026-08"
COMMIT = "2e9aa2e9b882383952c63d212add13eb80f46cf9"
SOURCE_URL = f"https://shopify.github.io/product-taxonomy/releases/{VERSION}/"
DOWNLOAD_URL = (
    f"https://raw.githubusercontent.com/Shopify/product-taxonomy/{COMMIT}/dist/en/taxonomy.json"
)
LICENSE_URL = f"https://raw.githubusercontent.com/Shopify/product-taxonomy/{COMMIT}/LICENSE"


def fetch(url):
    with urlopen(
        Request(url, headers={"User-Agent": "Kahoo taxonomy importer"}), timeout=120
    ) as response:
        return response.read()


def normalize(source):
    upstream = json.loads(source)
    if upstream["version"] != VERSION:
        raise ValueError(f"Expected Shopify {VERSION}, received {upstream['version']}")
    categories = [
        ProductCategory(**category, code=category["id"].rsplit("/", 1)[-1])
        for vertical in upstream["verticals"]
        for category in vertical["categories"]
    ]
    metadata = TaxonomyMetadata(
        version=VERSION,
        locale="en",
        source_url=SOURCE_URL,
        download_url=DOWNLOAD_URL,
        source_commit=COMMIT,
        source_sha256=hashlib.sha256(source).hexdigest(),
        categories=len(categories),
        attributes=len(upstream["attributes"]),
        values=sum(len(attribute["values"]) for attribute in upstream["attributes"]),
    )
    taxonomy = ProductTaxonomy(
        metadata=metadata, categories=categories, attributes=upstream["attributes"]
    )
    validate_links(taxonomy)
    return taxonomy


def validate_links(taxonomy):
    store = TaxonomyStore(taxonomy)
    category_ids = {category.id for category in taxonomy.categories}
    if len(store.categories) != len(taxonomy.categories):
        raise ValueError("Duplicate Shopify category IDs")
    if len(store.attributes_by_id) != len(taxonomy.attributes):
        raise ValueError("Duplicate Shopify attribute IDs")
    for category in taxonomy.categories:
        validate_category(category, category_ids, store)


def validate_category(category, category_ids, store):
    validate_parent(category, category_ids, store)
    for reference in category.attributes:
        if reference.id not in store.attributes_by_id:
            raise ValueError(f"Missing attribute {reference.id} for {category.code}")
        if store.attribute(reference.handle).id != reference.id:
            raise ValueError(f"Invalid attribute handle {reference.handle}")


def validate_parent(category, category_ids, store):
    if category.parent_id:
        if category.parent_id not in category_ids:
            raise ValueError(f"Missing parent for {category.code}")
        parent = store.category(category.parent_id.rsplit("/", 1)[-1])
        if category.level != parent.level + 1:
            raise ValueError(f"Invalid category depth for {category.code}")
    elif category.level != 0:
        raise ValueError(f"Invalid root depth for {category.code}")


def sync(args):
    if args.source:
        source = args.source.read_bytes()
        if args.source.suffix == ".gz":
            source = gzip.decompress(source)
    else:
        source = fetch(DOWNLOAD_URL)
    taxonomy = normalize(source)
    license_text = args.license.read_bytes() if args.license else fetch(LICENSE_URL)
    args.output.mkdir(parents=True, exist_ok=True)
    write_atomic(args.output / "upstream-taxonomy.json.gz", gzip.compress(source, mtime=0))
    write_atomic(
        args.output / "taxonomy.json.gz",
        gzip.compress(taxonomy.model_dump_json().encode(), mtime=0),
    )
    write_atomic(args.output / "LICENSE", license_text)
    write_atomic(
        args.output / "metadata.json", taxonomy.metadata.model_dump_json(indent=2).encode()
    )
    product_taxonomy.cache_clear()
    return taxonomy.metadata


def write_atomic(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
