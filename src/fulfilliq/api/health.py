"""Readiness logic is separate from routing and never creates an empty database."""

from pathlib import Path
from typing import Literal

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from fulfilliq.db.connection import make_engine
from fulfilliq.db.integrity import REQUIRED_TABLES
from fulfilliq.db.mart import SCHEMA_VERSION


def database_status(path: Path) -> Literal["ready", "missing", "invalid"]:
    if not path.is_file():
        return "missing"
    engine = make_engine(path, readonly=True)
    try:
        with engine.connect() as connection:
            if set(REQUIRED_TABLES) - set(inspect(connection).get_table_names()):
                return "invalid"
            versions = (
                connection.execute(text("SELECT schema_version FROM etl_runs")).scalars().all()
            )
            if versions != [SCHEMA_VERSION]:
                return "invalid"
            connection.execute(text("SELECT order_id FROM fact_orders LIMIT 1")).all()
        return "ready"
    except (SQLAlchemyError, OSError, ValueError):
        return "invalid"
    finally:
        engine.dispose()
