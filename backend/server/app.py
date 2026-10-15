import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from backend.config import PROJECT_ROOT
from backend.database import initialize_database
from backend.server.account_routes import router as account_router
from backend.server.instagram_routes import router as instagram_router
from backend.server.product_routes import router as product_router
from backend.server.routes import http_error_response, router, validation_error_response
from backend.server.saved_routes import router as saved_router
from backend.server.taxonomy_routes import router as taxonomy_router
from backend.services.taxonomy_repository import TaxonomyNotInitializedError

app = FastAPI(
    title="Kahoo",
    exception_handlers={
        RequestValidationError: validation_error_response,
        HTTPException: http_error_response,
        TaxonomyNotInitializedError: lambda _request, _error: JSONResponse(
            {"error": "taxonomy_not_initialized"}, status_code=503
        ),
    },
)
app.include_router(router)
app.include_router(account_router)
app.include_router(instagram_router)
app.include_router(saved_router)
app.include_router(taxonomy_router)
app.include_router(product_router)
app.mount("/", StaticFiles(directory=PROJECT_ROOT / "public", html=True), name="public")


def serve(args):
    initialize_database()
    uvicorn.run(app, host=args.host, port=args.port)
