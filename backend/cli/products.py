from threading import Event

from backend.services.product_vision import vision_configured
from backend.services.product_worker import (
    enqueue_existing_products,
    process_next_product,
    run_product_worker,
)


def enqueue(_args):
    return {"collections": enqueue_existing_products()}


def worker(args):
    if not vision_configured():
        raise ValueError("Configure PRODUCT_VISION_API_URL and PRODUCT_VISION_MODEL first")
    if args.once:
        enqueue_existing_products()
        processed = []
        for _ in range(args.limit):
            result = process_next_product()
            if result is None:
                break
            processed.append(result)
        return {"processed": processed}
    stop = Event()
    try:
        run_product_worker(stop, args.poll_seconds)
    except KeyboardInterrupt:
        stop.set()
    return None
