"""Consistent SQLite snapshot before the campaign schema is expanded."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text

from .campaign_designs import VERSION


def backup_before_migration(engine) -> Path | None:
    if (
        engine.dialect.name != "sqlite"
        or not engine.url.database
        or engine.url.database == ":memory:"
    ):
        return None
    tables = inspect(engine).get_table_names()
    if "merchant" not in tables:
        return None
    with engine.connect() as con:
        if (
            "schema_migration" in tables
            and con.execute(
                text("SELECT 1 FROM schema_migration WHERE version=:v"), {"v": VERSION}
            ).first()
        ):
            return None
        if not con.execute(text("SELECT 1 FROM merchant LIMIT 1")).first():
            return None
    source = Path(engine.url.database).resolve()
    folder = source.parent / "backups"
    folder.mkdir(exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"before-{VERSION}-{stamp}-{uuid.uuid4().hex[:8]}.db"
    with target.open("xb"):
        pass
    os.chmod(target, 0o600)
    with (
        sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original,
        sqlite3.connect(target) as snapshot,
    ):
        original.backup(snapshot)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Migration backup failed its integrity check")
    return target
