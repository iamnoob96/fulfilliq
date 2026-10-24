from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: Literal["FulfillIQ"] = "FulfillIQ"
    version: str
    database: Literal["ready", "missing", "invalid"]
