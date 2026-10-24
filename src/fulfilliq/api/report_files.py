"""Optional completed R outputs; paths are restricted to known report filenames."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from fulfilliq.config import Settings
from fulfilliq.modeling.training import dataset_identity

R_FILES = {"rules.csv", "comparison.json", "region-summary.csv", "delivery-duration.png",
           "regional-delay.png", "distance-duration.png", "seller-performance.png"}


class RReportStatus(BaseModel):
    available: bool
    message: str
    summary: dict
    files: list[str]


def report_files_router(settings: Settings):
    router = APIRouter(prefix="/api/v1/reports/r", tags=["Operations console"])
    folder = settings.artifact_dir / "r_analysis"

    def status():
        try:
            summary = json.loads((folder / "summary.json").read_text())
            if summary["dataset"]["source_sha256"] != dataset_identity(settings.database_path)["source_sha256"]:
                raise ValueError("R inputs differ from the current warehouse; regenerate outputs")
            return {"available": True, "message": "Completed optional R analysis", "summary": summary,
                    "files": sorted(name for name in R_FILES if (folder / name).is_file())}
        except (OSError, ValueError, KeyError, SQLAlchemyError) as exc:
            return {"available": False, "message": "Optional R outputs unavailable. Run the export, "
                    "R analysis and verification commands in r_analysis/README.md. " + str(exc),
                    "summary": {}, "files": []}

    @router.get("", response_model=RReportStatus)
    def r_status():
        return status()

    @router.get("/files/{filename}", response_class=FileResponse)
    def r_file(filename: str):
        if filename not in R_FILES or not status()["available"] or not (folder / filename).is_file():
            raise HTTPException(404, "Completed R report file not found")
        return FileResponse(folder / filename)

    return router
