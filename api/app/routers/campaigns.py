"""Tenant-scoped campaign design, image upload and membership endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from ..db import get_db
from ..schemas import (
    BarcodeVerification,
    CampaignCreate,
    CampaignOut,
    EnrollmentBatch,
    EnrollmentOut,
    EnrollmentUpdate,
    PassAssetOut,
    PassDesignIn,
)
from ..services import campaigns, pass_assets, passes
from .auth import authorize_merchant, current_user

router = APIRouter(prefix="/api/v1", tags=["campaign-designs"])


def access(db: Session, user: m.AdminUser, campaign_id: str, write: bool = False) -> m.Campaign:
    if write:
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    campaign = db.get(m.Campaign, campaign_id, populate_existing=True)
    if not campaign or campaign.deleted:
        raise HTTPException(404, "Campaign not found")
    authorize_merchant(campaign.merchant_id, user, db)
    return campaign


def sync_campaign(db: Session, campaign_id: str) -> None:
    rows = db.query(m.Pass).filter_by(campaign_id=campaign_id, status="active").all()
    for row in rows:
        row.updated_tag = passes._next_tag(db)
    campaign = db.get(m.Campaign, campaign_id)
    if not campaign.active:
        passes.mark_revoked(db, rows)
    db.commit()
    if not campaign.active:
        for row in rows:
            passes.revoke_pass(db, row.customer, row.id)
        return
    for customer_id in {row.customer_id for row in rows}:
        passes.update_customer_pass(db, db.get(m.Customer, customer_id))


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def detail(
    campaign_id: str, db: Session = Depends(get_db), user: m.AdminUser = Depends(current_user)
):
    return access(db, user, campaign_id)


@router.put("/campaigns/{campaign_id}", response_model=CampaignOut)
def edit(
    campaign_id: str,
    body: CampaignCreate,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
):
    """Atomically replace campaign configuration/design and optionally add customers."""
    campaign = access(db, user, campaign_id, True)
    campaign = campaigns.save_campaign(db, campaign.merchant, body, campaign)
    sync_campaign(db, campaign.id)
    return campaign


@router.post("/campaigns/{campaign_id}/archive")
def archive(
    campaign_id: str, db: Session = Depends(get_db), user: m.AdminUser = Depends(current_user)
) -> dict:
    """Keep history, stop accrual and revoke installed passes."""
    campaign = access(db, user, campaign_id, True)
    campaign.active = False
    rows = db.query(m.Pass).filter_by(campaign_id=campaign.id).all()
    passes.mark_revoked(db, rows)
    db.commit()
    return {
        "status": "archived",
        "pending_revocations": sum(not passes.revoke_pass(db, r.customer, r.id) for r in rows),
    }


@router.get("/campaigns/{campaign_id}/customers", response_model=list[EnrollmentOut])
def members(
    campaign_id: str, db: Session = Depends(get_db), user: m.AdminUser = Depends(current_user)
) -> list[dict]:
    access(db, user, campaign_id)
    return [
        campaigns.enrollment_out(db, row)
        for row in db.query(m.CampaignEnrollment).filter_by(campaign_id=campaign_id).all()
    ]


@router.post("/campaigns/{campaign_id}/customers", response_model=list[EnrollmentOut])
def enroll(
    campaign_id: str,
    body: EnrollmentBatch,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> list[dict]:
    """Idempotent batch enrollment. The whole batch succeeds or rolls back."""
    campaign = access(db, user, campaign_id, True)
    rows = []
    for customer_id in dict.fromkeys(body.customer_ids):
        customer = db.get(m.Customer, customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found in campaign merchant")
        rows.append(campaigns.enrollment(db, campaign, customer))
    db.commit()
    return [campaigns.enrollment_out(db, row) for row in rows]


@router.patch("/campaigns/{campaign_id}/customers/{customer_id}", response_model=EnrollmentOut)
def membership_status(
    campaign_id: str,
    customer_id: str,
    body: EnrollmentUpdate,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    campaign = access(db, user, campaign_id, True)
    row = (
        db.query(m.CampaignEnrollment)
        .filter_by(campaign_id=campaign_id, customer_id=customer_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Enrollment not found")
    if body.status == "active" and (
        row.customer.deleted or not campaign.active or campaign.lifecycle == "draft"
    ):
        raise HTTPException(409, "Customer or campaign inactive")
    row.status = body.status
    row.updated_at = m._now()
    affected = db.query(m.Pass).filter_by(customer_id=customer_id, campaign_id=campaign_id).all()
    if body.status != "active":
        passes.mark_revoked(db, affected)
    db.commit()
    pending = (
        sum(not passes.revoke_pass(db, r.customer, r.id) for r in affected)
        if body.status != "active"
        else 0
    )
    return {**campaigns.enrollment_out(db, row), "pending_revocations": pending}


@router.get("/customers/{customer_id}/campaigns", response_model=list[EnrollmentOut])
def customer_campaigns(
    customer_id: str, db: Session = Depends(get_db), user: m.AdminUser = Depends(current_user)
) -> list[dict]:
    customer = db.get(m.Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(customer.merchant_id, user, db)
    return [
        campaigns.enrollment_out(db, r)
        for r in db.query(m.CampaignEnrollment).filter_by(customer_id=customer_id).all()
    ]


@router.get("/campaigns/{campaign_id}/customers/{customer_id}/passes")
def member_passes(
    campaign_id: str,
    customer_id: str,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> list[dict]:
    from .assignments import describe

    access(db, user, campaign_id)
    row = (
        db.query(m.CampaignEnrollment)
        .filter_by(campaign_id=campaign_id, customer_id=customer_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Enrollment not found")
    return [
        describe(r)
        for r in db.query(m.Pass).filter_by(campaign_id=campaign_id, customer_id=customer_id).all()
    ]


@router.post(
    "/merchants/{merchant_id}/pass-assets",
    status_code=201,
    response_model=PassAssetOut,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}}
                for kind in ("image/png", "image/jpeg", "image/webp")
            },
        }
    },
)
async def upload(
    merchant_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    """Upload an image body. Content is decoded, normalized to PNG and initially private."""
    authorize_merchant(merchant_id, user, db)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > settings.pass_asset_max_bytes:
            raise HTTPException(413, "Image exceeds PASS_ASSET_MAX_BYTES")
    from .merchants import lock_live_merchant

    lock_live_merchant(db, merchant_id)
    asset = pass_assets.store_image(db, merchant_id, bytes(data))
    try:
        result = pass_assets.describe(asset)
    except ValueError:
        raise HTTPException(503, "Configure PUBLIC_API_URL with a public HTTPS base URL")
    db.commit()
    return result


@router.get("/merchants/{merchant_id}/pass-assets/{asset_id}", response_model=PassAssetOut)
def asset_info(
    merchant_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    asset = db.get(m.PassAsset, asset_id)
    if not asset or asset.merchant_id != merchant_id:
        raise HTTPException(404, "Asset not found")
    return pass_assets.describe(asset)


@router.delete("/merchants/{merchant_id}/pass-assets/{asset_id}")
def delete_asset(
    merchant_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    from .merchants import lock_live_merchant

    lock_live_merchant(db, merchant_id)
    authorize_merchant(merchant_id, user, db)
    asset = db.get(m.PassAsset, asset_id)
    if not asset or asset.merchant_id != merchant_id:
        raise HTTPException(404, "Asset not found")
    if asset.campaign_id:
        raise HTTPException(409, "Replace or detach this asset through the campaign design")
    db.delete(asset)
    db.commit()
    return {"status": "deleted"}


@router.put("/campaigns/{campaign_id}/design", response_model=CampaignOut)
def replace_design(
    campaign_id: str,
    body: PassDesignIn,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
):
    campaign = access(db, user, campaign_id, True)
    if campaign.lifecycle != "draft" and (not body.logo_asset_id or not body.hero_asset_id):
        raise HTTPException(
            422, "A completed design requires both images; replace instead of removing"
        )
    campaigns.apply_design(db, campaign, body)
    sync_campaign(db, campaign.id)
    return campaign


@router.get("/public/pass-assets/{asset_id}", tags=["public-assets"])
def published_asset(asset_id: str, db: Session = Depends(get_db)) -> Response:
    asset = db.get(m.PassAsset, asset_id)
    campaign = db.get(m.Campaign, asset.campaign_id) if asset and asset.campaign_id else None
    if (
        not asset
        or not asset.published
        or not campaign
        or campaign.deleted
        or campaign.merchant.status == "deleted"
    ):
        raise HTTPException(404, "Asset not found")
    return Response(
        asset.content,
        media_type=asset.content_type,
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/merchants/{merchant_id}/enrollments/verify", response_model=EnrollmentOut)
def verify_barcode(
    merchant_id: str,
    body: BarcodeVerification,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    """Identify an active membership. This is not authorization to debit/redeem points."""
    authorize_merchant(merchant_id, user, db)
    row = (
        db.query(m.CampaignEnrollment)
        .join(m.Campaign)
        .filter(
            m.Campaign.merchant_id == merchant_id,
            m.CampaignEnrollment.barcode_token == body.token,
            m.CampaignEnrollment.status == "active",
            m.Campaign.active.is_(True),
            m.Campaign.deleted.is_(False),
        )
        .first()
    )  # noqa: E712
    if not row or row.customer.deleted:
        raise HTTPException(404, "Active enrollment not found")
    return campaigns.enrollment_out(db, row)


@router.get("/merchants/{merchant_id}/pass-assets/{asset_id}/content")
def private_asset(
    merchant_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> Response:
    authorize_merchant(merchant_id, user, db)
    asset = db.get(m.PassAsset, asset_id)
    if not asset or asset.merchant_id != merchant_id:
        raise HTTPException(404, "Asset not found")
    return Response(
        asset.content,
        media_type=asset.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
