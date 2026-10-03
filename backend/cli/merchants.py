from backend.instagram import normalize_identifier
from backend.services.merchants import add_or_refresh_merchant, admin_merchants, remove_merchant


def add(args):
    return add_or_refresh_merchant(
        args.identifier, args.category, args.name, args.description, args.city
    )


def import_file(args):
    identifiers = list(
        dict.fromkeys(
            normalize_identifier(value) for value in args.source.read_text(encoding="utf-8").split()
        )
    )
    results = []
    for identifier in identifiers:
        try:
            results.append(
                add_or_refresh_merchant(identifier, category_code=args.category, city=args.city)
            )
        except (ValueError, OSError) as error:
            results.append({"handle": identifier, "error": str(error)})
    return {"results": results, "failed": sum("error" in item for item in results)}


def list_merchants(args):
    return admin_merchants(args.query, args.limit, args.offset)


def remove(args):
    merchant = remove_merchant(args.merchant_id)
    if not merchant:
        raise ValueError("merchant not found")
    return {"removed": merchant}
