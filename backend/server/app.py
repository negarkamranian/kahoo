import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from backend.config import PROJECT_ROOT
from backend.database import initialize_database
from backend.server.routes import http_error_response, router, validation_error_response

app = FastAPI(
    title="Kahoo",
    exception_handlers={
        RequestValidationError: validation_error_response,
        HTTPException: http_error_response,
    },
)
app.include_router(router)
app.mount("/", StaticFiles(directory=PROJECT_ROOT / "public", html=True), name="public")


def serve(args):
    initialize_database()
    uvicorn.run(app, host=args.host, port=args.port)
