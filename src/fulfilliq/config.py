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
        return self.processed_dir / "operations.sqlite3"
