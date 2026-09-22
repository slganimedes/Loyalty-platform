"""Campaign design and explicit membership domain operations. Caller owns transaction."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import CampaignCreate, PassDesignIn


def points_balance(db: Session, campaign_id: str, customer_id: str) -> int:
    return int(
        db.query(func.coalesce(func.sum(m.Movement.points_delta), 0))
        .filter_by(campaign_id=campaign_id, customer_id=customer_id)
        .scalar()
    )


def enrollment(db: Session, campaign: m.Campaign, customer: m.Customer) -> m.CampaignEnrollment:
    if customer.merchant_id != campaign.merchant_id or customer.deleted or campaign.deleted:
        raise HTTPException(404, "Customer not found in campaign merchant")
    if campaign.lifecycle == "draft" or not campaign.active:
        raise HTTPException(409, "Campaign must be ready and active before enrollment")
    row = (
        db.query(m.CampaignEnrollment)
        .filter_by(campaign_id=campaign.id, customer_id=customer.id)
        .first()
    )
    if row and row.status != "active":
        raise HTTPException(409, "Enrollment exists; change its status explicitly")
    if not row:
        row = m.CampaignEnrollment(campaign_id=campaign.id, customer_id=customer.id)
        db.add(row)
        db.flush()
    return row


def enrollment_out(db: Session, row: m.CampaignEnrollment) -> dict:
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "customer_id": row.customer_id,
        "campaign_name": row.campaign.name,
        "customer_name": row.customer.name or row.customer.customer_code,
        "customer_code": row.customer.customer_code,
        "status": row.status,
        "enrolled_at": row.enrolled_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "points_balance": points_balance(db, row.campaign_id, row.customer_id),
    }


def apply_design(db: Session, campaign: m.Campaign, body: PassDesignIn) -> None:
    design = campaign.design
    if not design:
        design = m.PassDesign(campaign_id=campaign.id)
        db.add(design)
        campaign.design = design
    new_assets = {body.logo_asset_id, body.hero_asset_id} - {None}
    if new_assets:
        from .pass_assets import public_url

        try:
            public_url(next(iter(new_assets)))
        except ValueError:
            raise HTTPException(503, "Configure PUBLIC_API_URL with a public HTTPS base URL")
    if body.logo_asset_id and body.logo_asset_id == body.hero_asset_id:
        raise HTTPException(422, "Use separate logo and hero assets")
    for asset_id in new_assets:
        asset = db.get(m.PassAsset, asset_id)
        if (
            not asset
            or asset.merchant_id != campaign.merchant_id
            or asset.campaign_id not in (None, campaign.id)
        ):
            raise HTTPException(404, "Asset not found in campaign merchant")
        asset.campaign_id, asset.published, asset.retired_at = (
            campaign.id,
            campaign.lifecycle != "draft",
            None,
        )
    for asset_id in {design.logo_asset_id, design.hero_asset_id} - new_assets - {None}:
        db.get(m.PassAsset, asset_id).retired_at = m._now()
    for key, value in body.model_dump().items():
        setattr(design, key, value)
    design.legacy_review_required = False


def save_campaign(
    db: Session, merchant: m.Merchant, body: CampaignCreate, campaign: m.Campaign | None = None
) -> m.Campaign:
    if not campaign:
        campaign = m.Campaign(merchant_id=merchant.id)
        db.add(campaign)
    elif campaign.type != body.type:
        raise HTTPException(409, "Campaign type cannot change; create a new campaign")
    lifecycle = body.lifecycle or ("ready" if body.design else "draft")
    if lifecycle == "ready" and (
        not body.design or not body.design.logo_asset_id or not body.design.hero_asset_id
    ):
        raise HTTPException(422, "Ready campaigns require logo, hero image and pass design")
    if (
        lifecycle == "draft"
        and campaign.id
        and db.query(m.CampaignEnrollment).filter_by(campaign_id=campaign.id).first()
    ):
        raise HTTPException(409, "A campaign with enrollments cannot return to draft")
    campaign.name, campaign.description, campaign.type = body.name, body.description, body.type
    campaign.config, campaign.lifecycle = body.config, lifecycle
    campaign.active = body.active and lifecycle != "draft"
    db.flush()
    apply_design(db, campaign, body.design or PassDesignIn(background_color=merchant.pass_color))
    db.flush()
    for customer_id in set(body.customer_ids):
        customer = db.get(m.Customer, customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found in campaign merchant")
        enrollment(db, campaign, customer)
    return campaign


def cancel_enrollments(
    db: Session, *, campaign_id: str | None = None, customer_id: str | None = None
) -> None:
    query = db.query(m.CampaignEnrollment)
    if campaign_id:
        query = query.filter_by(campaign_id=campaign_id)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    query.update({"status": "cancelled", "updated_at": m._now()}, synchronize_session=False)
