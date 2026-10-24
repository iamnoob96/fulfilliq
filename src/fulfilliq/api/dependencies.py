"""Read-only readiness checks. Missing artifacts never trigger generation."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from fulfilliq.analytics.store import load_insight
from fulfilliq.api.health import database_status
from fulfilliq.config import Settings
from fulfilliq.modeling.inference import RiskService


class DependencyState(BaseModel):
    name: str
    ready: bool
    detail: str


class DependenciesResponse(BaseModel):
    dependencies: list[DependencyState]
    review_writes_enabled: bool
    interpretation: str


def dependency_router(settings: Settings):
    router = APIRouter(prefix="/api/v1/console", tags=["Operations console"])

    @router.get("/dependencies", response_model=DependenciesResponse)
    def dependencies():
        status = database_status(settings.database_path)
        result = [{"name": "warehouse", "ready": status == "ready", "detail": status}]
        for name in ("model", "rules", "segments", "anomalies", "reviews"):
            try:
                if name == "model":
                    detail = RiskService(settings.artifact_dir, settings.database_path).load()["model_version"]
                else:
                    detail = load_insight(settings.artifact_dir, name, settings.database_path)["created_at_utc"]
                result.append({"name": name, "ready": True, "detail": detail})
            except (OSError, ValueError, SQLAlchemyError) as exc:
                result.append({"name": name, "ready": False, "detail": str(exc)})
        return {"dependencies": result, "review_writes_enabled": bool(settings.write_token),
                "interpretation": "Read-only local checks. Missing models/insights require explicit offline "
                "preparation; the console never trains or rebuilds them. R reports are optional."}

    return router
