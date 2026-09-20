"""Explicit campaign/customer pass assignments; reading never issues a pass."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import PassAssignment
from ..services import passes
from .auth import authorize_merchant, current_user, merchant_access

router = APIRouter(prefix="/api/v1", tags=["campaign-passes"])


def describe(row: models.Pass) -> dict:
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_code": row.customer.customer_code,
        "customer_deleted": row.customer.deleted,
        "campaign_id": row.campaign_id,
        "campaign_name": row.campaign.name if row.campaign else None,
        "campaign_deleted": row.campaign.deleted if row.campaign else False,
        "platform": row.platform,
        "status": row.status,
        "sync_pending": row.updated_tag != row.synced_tag,
        "legacy": row.campaign_id is None,
    }


@router.get("/merchants/{merchant_id}/passes")
def list_passes(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> list[dict]:
    rows = (
        db.query(models.Pass)
        .join(models.Customer)
        .filter(models.Customer.merchant_id == merchant_id)
        .all()
    )
    return [describe(row) for row in rows]


@passes.serialize_customer
def assign(db: Session, customer: models.Customer, body: PassAssignment) -> models.Pass:
    # Serialize SQLite writers so assignment cannot race parent deletion.
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    db.refresh(customer)
    campaign = db.get(models.Campaign, body.campaign_id)
    if customer.deleted:
        raise HTTPException(404, "Customer deleted")
    if not campaign or campaign.merchant_id != customer.merchant_id or campaign.deleted:
        raise HTTPException(404, "Campaign not found in customer's merchant")
    if not campaign.active or customer.merchant.status != "active":
        raise HTTPException(409, "Campaign or merchant inactive")
    cfg = passes._wallet_config(db)
    if not cfg or not getattr(cfg, f"{body.platform}_enabled"):
        raise HTTPException(409, "Wallet provider disabled")
    row = passes.ensure_pass(
        db, customer, body.platform, passes.provider_config(cfg, body.platform), campaign.id
    )
    db.commit()
    return row


@router.post("/customers/{customer_id}/passes")
def assign_pass(
    customer_id: str,
    body: PassAssignment,
    db: Session = Depends(get_db),
    user: models.AdminUser = Depends(current_user),
) -> dict:
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(customer.merchant_id, user, db)
    row = assign(db, customer, body)
    links = passes.issue_pass_links(db, customer, row.id)
    return {"pass": describe(row), "url": links.get(row.id), "provider_synced": row.id in links}


@router.post("/customers/{customer_id}/passes/{pass_id}/link")
def pass_link(
    customer_id: str,
    pass_id: str,
    db: Session = Depends(get_db),
    user: models.AdminUser = Depends(current_user),
) -> dict:
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(customer.merchant_id, user, db)
    row = db.get(models.Pass, pass_id)
    if not row or row.customer_id != customer_id:
        raise HTTPException(404, "Pass not found")
    if row.status != "active" or customer.deleted or (row.campaign and row.campaign.deleted):
        raise HTTPException(410, "Pass revoked")
    links = passes.issue_pass_links(db, customer, pass_id)
    return {"pass": describe(row), "url": links.get(row.id if row.campaign_id else row.platform)}
