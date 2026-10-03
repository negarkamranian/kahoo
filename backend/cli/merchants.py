from backend.models.merchants import AdminMerchantQuery, ImportBatch, MerchantImport
from backend.services.merchants import add_or_refresh_merchant, admin_merchants, remove_merchant


def add(args):
    return add_or_refresh_merchant(
        MerchantImport(
            identifier=args.identifier,
            category_code=args.category,
            city=args.city,
        )
    )


def import_file(args):
    identifiers = list(dict.fromkeys(args.source.read_text(encoding="utf-8").split()))
    results = []
    for identifier in identifiers:
        request = MerchantImport(identifier=identifier, category_code=args.category, city=args.city)
        results.append(add_or_refresh_merchant(request))
    return ImportBatch(results=results, failed=0)


def list_merchants(args):
    return admin_merchants(
        AdminMerchantQuery(query=args.query, limit=args.limit, offset=args.offset)
    )


def remove(args):
    merchant = remove_merchant(args.merchant_id)
    if not merchant:
        raise ValueError("merchant not found")
    return {"removed": merchant}
