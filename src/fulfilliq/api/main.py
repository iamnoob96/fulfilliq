from fastapi import FastAPI, Response

from fulfilliq import __version__
from fulfilliq.api.health import database_status
from fulfilliq.api.schemas import HealthResponse
from fulfilliq.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="FulfillIQ",
        version=__version__,
        description="Phase 1: Olist ingestion and a historical logistics data foundation.",
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

    return app


app = create_app()
