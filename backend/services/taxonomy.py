from functools import lru_cache

from backend.models.taxonomy import CategoryAttribute, ProductCategoryTree
from backend.services.taxonomy_repository import active_taxonomy_id, load_taxonomy


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


def product_taxonomy():
    return taxonomy_store(active_taxonomy_id())


@lru_cache(maxsize=2)
def taxonomy_store(release_id):
    return TaxonomyStore(load_taxonomy(release_id))
