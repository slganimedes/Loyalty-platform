"""Expand/migrate campaign memberships without distributing ambiguous balances."""

import io
from pathlib import Path

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, text
from sqlalchemy.orm import Session

VERSION = "20260921_campaign_designs"


def inherited_images(db, merchant, campaign, design):
    """Keep originals and provide explicit reviewable fallbacks for incomplete old designs."""
    from ..config import settings
    from ..services.pass_assets import store_image

    raw = merchant.logo_data
    if not raw and merchant.pass_logo_path:
        root = Path(settings.assets_dir).resolve()
        path = (root / merchant.pass_logo_path).resolve()
        if path.is_relative_to(root) and path.is_file():
            raw = path.read_bytes()
    for kind, size in (("logo", (128, 128)), ("hero", (800, 240))):
        output = io.BytesIO()
        Image.new("RGB", size, merchant.pass_color or "#373839").save(output, "PNG")
        try:
            asset = store_image(
                db, merchant.id, raw if raw and kind == "logo" else output.getvalue()
            )
        except HTTPException:
            # Keep the original merchant BLOB/path untouched for manual recovery.
            asset = store_image(db, merchant.id, output.getvalue())
        asset.campaign_id, asset.published = campaign.id, True
        setattr(design, f"{kind}_asset_id", asset.id)
    design.legacy_review_required = True


def migrate(engine) -> None:
    from .. import models as m

    with engine.begin() as con:
        for table, column in [
            ("customer", "merchant_id"),
            ("campaign", "merchant_id"),
            ("pass", "campaign_id"),
            ("pass", "customer_id"),
            ("pass", "enrollment_id"),
            ("movement", "campaign_id"),
            ("movement", "customer_id"),
        ]:
            con.execute(
                text(f'CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON "{table}" ({column})')
            )
        for operation in ("INSERT", "UPDATE"):
            con.execute(
                text(f"""CREATE TRIGGER IF NOT EXISTS enrollment_tenant_{operation.lower()}
                BEFORE {operation} ON campaign_enrollment
                WHEN (SELECT merchant_id FROM campaign WHERE id = NEW.campaign_id)
                    != (SELECT merchant_id FROM customer WHERE id = NEW.customer_id)
                BEGIN SELECT RAISE(ABORT, 'Enrollment merchant mismatch'); END""")
            )
    with Session(engine) as db:
        if db.get(m.SchemaMigration, VERSION):
            return
        # Before this migration every merchant campaign applied to every customer.
        # Materialize precisely that implicit relationship; balances remain in the ledger.
        for campaign in db.query(m.Campaign).all():
            merchant = db.get(m.Merchant, campaign.merchant_id)
            if not db.get(m.PassDesign, campaign.id):
                design = m.PassDesign(campaign_id=campaign.id, background_color=merchant.pass_color)
                db.add(design)
                inherited_images(db, merchant, campaign, design)
            for customer in db.query(m.Customer).filter_by(merchant_id=merchant.id).all():
                enrollment = (
                    db.query(m.CampaignEnrollment)
                    .filter_by(campaign_id=campaign.id, customer_id=customer.id)
                    .first()
                )
                if not enrollment:
                    first = (
                        db.query(func.min(m.Movement.created_at))
                        .filter_by(campaign_id=campaign.id, customer_id=customer.id)
                        .scalar()
                    )
                    enrollment = m.CampaignEnrollment(
                        campaign_id=campaign.id,
                        customer_id=customer.id,
                        enrolled_at=first or customer.created_at,
                        status="cancelled"
                        if customer.deleted or campaign.deleted or merchant.status == "deleted"
                        else "active",
                    )
                    db.add(enrollment)
                    db.flush()
                for row in (
                    db.query(m.Pass)
                    .filter_by(campaign_id=campaign.id, customer_id=customer.id)
                    .all()
                ):
                    row.enrollment_id = enrollment.id
        for customer in db.query(m.Customer).all():
            attributed = (
                db.query(func.coalesce(func.sum(m.Movement.points_delta), 0))
                .filter(m.Movement.customer_id == customer.id, m.Movement.campaign_id.is_not(None))
                .scalar()
            )
            customer.legacy_points_balance = customer.points_balance - int(attributed)
        db.add(m.SchemaMigration(version=VERSION))
        db.commit()
