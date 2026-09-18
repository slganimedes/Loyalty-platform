"""Database engine, session and Base declarative class."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import settings

# check_same_thread is required for SQLite used by multiple threads (uvicorn workers)
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Imports models so they register on Base.metadata."""
    from . import models  # noqa: F401  (ensures models are imported)

    Base.metadata.create_all(bind=engine)
    # Additive migrations preserve pilot data created by the original scaffold.
    additions = {
        "merchant": {"logo_data": "BLOB"},
        "pass": {
            "auth_token": "VARCHAR",
            "updated_tag": "INTEGER DEFAULT 0",
            "synced_tag": "INTEGER DEFAULT 0",
            "pass_type_id": "VARCHAR",
        },
        "movement": {"campaign_id": "VARCHAR REFERENCES campaign(id)", "description": "VARCHAR"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {c["name"] for c in inspect(connection).get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(
                        text(f'ALTER TABLE "{table}" ADD COLUMN {column} {definition}')
                    )
