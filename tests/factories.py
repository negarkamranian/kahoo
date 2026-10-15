from backend.cli.taxonomy import VERSION


def upstream_fixture():
    attribute = {
        "id": "gid://shopify/TaxonomyAttribute/1",
        "name": "Color",
        "handle": "color",
        "description": "Product color",
        "extended_attributes": [{"name": "Liner color", "handle": "liner-color"}],
        "values": [
            {"id": "gid://shopify/TaxonomyValue/1", "name": "Blue", "handle": "color__blue"}
        ],
    }
    categories = []
    for level in range(8):
        code = "aa" + "-1" * level
        categories.append(
            {
                "id": f"gid://shopify/TaxonomyCategory/{code}",
                "level": level,
                "name": f"Category {level}",
                "full_name": f"Apparel > Category {level}",
                "parent_id": categories[-1]["id"] if categories else None,
                "attributes": [
                    {
                        "id": attribute["id"],
                        "name": "Liner color",
                        "handle": "liner-color",
                        "description": "Category-specific color description",
                        "extended": True,
                    }
                ],
                "return_reasons": [{"name": "Retained only in upstream"}],
            }
        )
    return {
        "version": VERSION,
        "verticals": [{"categories": categories}],
        "attributes": [attribute],
    }
