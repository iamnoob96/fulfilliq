"""Paths are relative to the working directory unless explicitly configured."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("FULFILIQ_DATA_DIR", "data")).resolve()
    )
    artifact_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("FULFILIQ_ARTIFACT_DIR", "artifacts")).resolve()
    )
    write_token: str = field(default_factory=lambda: os.environ.get("FULFILIQ_WRITE_TOKEN", ""), repr=False)
    scoring_max_orders: int = field(default_factory=lambda: int(os.environ.get("FULFILIQ_SCORING_MAX_ORDERS", "2000")))
    operational_dir: Path | None = field(default_factory=lambda: Path(os.environ["FULFILIQ_OPERATIONS_DIR"]).resolve()
                                        if os.environ.get("FULFILIQ_OPERATIONS_DIR") else None)

    def __post_init__(self):
        if not 1 <= self.scoring_max_orders <= 5000:
            raise ValueError("FULFILIQ_SCORING_MAX_ORDERS must be within 1–5000")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def database_path(self) -> Path:
        return self.processed_dir / "fulfilliq.sqlite3"

    @property
    def review_database_path(self) -> Path:
        return (self.operational_dir or self.processed_dir) / "operations.sqlite3"

    @property
    def scoring_database_path(self) -> Path:
        return (self.operational_dir or self.processed_dir) / "scoring.sqlite3"
