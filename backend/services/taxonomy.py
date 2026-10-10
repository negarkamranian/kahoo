"""Offline product taxonomy access, including category-specific extended attributes."""

import gzip
from functools import lru_cache

from backend.config import PROJECT_ROOT
from backend.models.taxonomy import CategoryAttribute, ProductCategoryTree, ProductTaxonomy

TAXONOMY_PATH = PROJECT_ROOT / "data/shopify/2026-08/taxonomy.json.gz"


class TaxonomyStore:
    def __init__(self, taxonomy):
        self.taxonomy = taxonomy
        self.categories = {category.code: category for category in taxonomy.categories}
        self.attributes = {attribute.handle: attribute for attribute in taxonomy.attributes}
        self.attributes_by_id = {attribute.id: attribute for attribute in taxonomy.attributes}
        self.aliases = {
            alias.handle: (attribute, alias)
            for attribute in taxonomy.attributes
            for alias in attribute.extended_attributes
        }

    def category(self, code):
        return self.categories[code]

    def attribute(self, handle):
        if handle in self.attributes:
            return self.attributes[handle]
        attribute, alias = self.aliases[handle]
        return attribute.model_copy(update={"name": alias.name, "handle": alias.handle})

    def category_attributes(self, code):
        return [
            CategoryAttribute(
                **reference.model_dump(), values=self.attributes_by_id[reference.id].values
            )
            for reference in self.category(code).attributes
        ]

    def tree(self):
        nodes = {
            category.id: ProductCategoryTree(**category.model_dump())
            for category in self.taxonomy.categories
        }
        roots = []
        for category in self.taxonomy.categories:
            node = nodes[category.id]
            if category.parent_id:
                nodes[category.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots


@lru_cache(maxsize=1)
def product_taxonomy():
    with gzip.open(TAXONOMY_PATH, "rb") as source:
        return TaxonomyStore(ProductTaxonomy.model_validate_json(source.read()))
