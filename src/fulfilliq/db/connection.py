"""SQLite connections always enforce referential integrity."""

from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event


def make_engine(path: Path, *, readonly: bool = False) -> Engine:
    path = path.resolve()
    if readonly:
        # URI mode=ro avoids silently creating a database during health/stat checks.
        from urllib.parse import quote

        # A structured URL prevents SQLAlchemy from decoding URI metacharacters early.
        url = URL.create(
            "sqlite",
            database=f"file:{quote(str(path), safe='/')}",
            query={"mode": "ro", "uri": "true"},
        )
        engine = create_engine(url)
    else:
        engine = create_engine(URL.create("sqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine
