"""Additive outbox tables are created by metadata; record completion idempotently."""

from sqlalchemy import text
from sqlalchemy.orm import Session

VERSION = "20260925_notifications"


def migrate(engine) -> None:
    from .. import models as m

    with Session(engine) as db:
        db.execute(text("BEGIN IMMEDIATE"))
        if not db.get(m.SchemaMigration, VERSION):
            db.add(m.SchemaMigration(version=VERSION))
        db.commit()
