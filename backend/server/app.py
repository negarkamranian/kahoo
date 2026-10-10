from contextlib import asynccontextmanager
from threading import Event, Thread

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from backend.config import PROJECT_ROOT
from backend.database import initialize_database
from backend.server.account_routes import router as account_router
from backend.server.product_routes import router as product_router
from backend.server.routes import http_error_response, router, validation_error_response
from backend.server.saved_routes import router as saved_router
from backend.server.taxonomy_routes import router as taxonomy_router
from backend.services.product_vision import vision_configured
from backend.services.product_worker import run_product_worker


@asynccontextmanager
async def lifespan(_app):
    stop = Event()
    worker = None
    if vision_configured():
        worker = Thread(
            target=run_product_worker, args=(stop,), name="product-enrichment", daemon=True
        )
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.join(timeout=1)


app = FastAPI(
    title="Kahoo",
    lifespan=lifespan,
    exception_handlers={
        RequestValidationError: validation_error_response,
        HTTPException: http_error_response,
    },
)
app.include_router(router)
app.include_router(account_router)
app.include_router(saved_router)
app.include_router(taxonomy_router)
app.include_router(product_router)
app.mount("/", StaticFiles(directory=PROJECT_ROOT / "public", html=True), name="public")


def serve(args):
    initialize_database()
    uvicorn.run(app, host=args.host, port=args.port)
