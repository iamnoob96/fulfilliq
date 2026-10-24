import sqlite3

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fulfilliq import __version__
from fulfilliq.analytics.store import InsightUnavailable
from fulfilliq.api.console_routes import console_router
from fulfilliq.api.dependencies import dependency_router
from fulfilliq.api.explorer_routes import explorer_router
from fulfilliq.api.health import database_status
from fulfilliq.api.intelligence_schemas import ErrorResponse
from fulfilliq.api.report_files import report_files_router
from fulfilliq.api.routes import intelligence_router
from fulfilliq.api.schemas import HealthResponse
from fulfilliq.api.scoring_routes import scoring_router
from fulfilliq.config import Settings
from fulfilliq.logging_config import configure_logging
from fulfilliq.modeling.inference import ModelUnavailable
from fulfilliq.operations.jobs import JobConflict, JobNotFound


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    settings = settings or Settings()
    app = FastAPI(
        title="FulfillIQ",
        version=__version__,
        description="Olist logistics intelligence: purchase-time risk, historical fulfillment "
        "analytics, data mining and Portuguese reviews. Train/build offline with the CLI.",
        responses={
            503: {
                "model": ErrorResponse,
                "description": "Required database/model/report unavailable",
            },
            422: {"model": ErrorResponse, "description": "Invalid input or incoherent date filter"},
        },
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
        responses={503: {"model": HealthResponse, "description": "Database is not ready"}},
    )
    def health(response: Response) -> HealthResponse:
        database = database_status(settings.database_path)
        if database != "ready":
            response.status_code = 503
        return HealthResponse(
            status="ok" if database == "ready" else "degraded",
            version=__version__,
            database=database,
        )

    @app.exception_handler(ModelUnavailable)
    @app.exception_handler(InsightUnavailable)
    async def unavailable(_request: Request, exc: Exception):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(OSError)
    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, _exc: Exception):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Required local database or artifact "
                "is unavailable. Run 'fulfilliq ingest', 'train' and 'build-insights'."
            },
        )

    @app.exception_handler(ValueError)
    async def invalid_input(_request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(JobNotFound)
    async def job_not_found(_request: Request, exc: Exception):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(JobConflict)
    async def job_conflict(_request: Request, exc: Exception):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(intelligence_router(settings))
    app.include_router(console_router(settings))
    app.include_router(explorer_router(settings))
    app.include_router(report_files_router(settings))
    app.include_router(dependency_router(settings))
    app.include_router(scoring_router(settings))
    return app


app = create_app()
