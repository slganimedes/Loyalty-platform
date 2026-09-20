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
        "campaign": {
            "deleted": "BOOLEAN NOT NULL DEFAULT 0",
            "name": "VARCHAR NOT NULL DEFAULT 'Campaign'",
        },
        "customer": {"deleted": "BOOLEAN NOT NULL DEFAULT 0"},
        "merchant": {"logo_data": "BLOB"},
        "pass": {
            "campaign_id": "VARCHAR REFERENCES campaign(id)",
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
    _migrate_campaign_passes()


def _migrate_campaign_passes() -> None:
    """Remove the old customer/provider uniqueness without losing pass/device IDs."""
    constraints = inspect(engine).get_unique_constraints("pass")
    if not any(set(c["column_names"]) == {"customer_id", "platform"} for c in constraints):
        return
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Campaign pass migration currently requires SQLite")
    raw = engine.raw_connection()
    try:
        raw.rollback()
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("""CREATE TABLE pass_campaign_migration (
            id VARCHAR PRIMARY KEY NOT NULL,
            customer_id VARCHAR NOT NULL REFERENCES customer(id),
            campaign_id VARCHAR REFERENCES campaign(id),
            platform VARCHAR NOT NULL, external_pass_id VARCHAR, status VARCHAR,
            auth_token VARCHAR, updated_tag INTEGER, synced_tag INTEGER, pass_type_id VARCHAR
        )""")
        columns = "id, customer_id, campaign_id, platform, external_pass_id, status, auth_token, updated_tag, synced_tag, pass_type_id"
        cursor.execute(
            f'INSERT INTO pass_campaign_migration ({columns}) SELECT {columns} FROM "pass"'
        )
        cursor.execute('DROP TABLE "pass"')
        cursor.execute('ALTER TABLE pass_campaign_migration RENAME TO "pass"')
        cursor.execute("""CREATE UNIQUE INDEX uq_active_campaign_pass ON "pass"
            (customer_id, campaign_id, platform) WHERE status = 'active' AND campaign_id IS NOT NULL""")
        if cursor.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key validation failed during pass migration")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.close()
