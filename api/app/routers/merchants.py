import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import (
    CampaignCreate,
    CampaignOut,
    CouponCreate,
    CouponOut,
    CustomerCreate,
    CustomerOut,
    MerchantCreate,
    MerchantOut,
    MerchantUpdate,
)
from ..services import passes
from ..services.logos import decode_logo
from .auth import current_user, merchant_access, super_admin

router = APIRouter(prefix="/api/v1", tags=["merchants"])


def lock_live_merchant(db: Session, merchant_id: str) -> models.Merchant:
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    merchant = db.get(models.Merchant, merchant_id, populate_existing=True)
    if not merchant or merchant.status == "deleted":
        raise HTTPException(404, "Merchant not found")
    return merchant


# ---------- Merchants ----------
@router.post("/merchants", response_model=MerchantOut)
def create_merchant(
    body: MerchantCreate,
    db: Session = Depends(get_db),
    user: models.AdminUser = Depends(super_admin),
) -> models.Merchant:
    values = body.model_dump(exclude={"logo_base64"})
    if body.logo_base64 is not None:
        values.update(logo_data=decode_logo(body.logo_base64), pass_logo_path=None)
    m = models.Merchant(**values)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.get("/merchants", response_model=list[MerchantOut])
def list_merchants(
    db: Session = Depends(get_db), user: models.AdminUser = Depends(current_user)
) -> list[models.Merchant]:
    query = db.query(models.Merchant).filter(models.Merchant.status != "deleted")
    if user.role != "super_admin":
        query = query.filter_by(id=user.merchant_id)
    return query.all()


@router.get("/merchants/{merchant_id}", response_model=MerchantOut)
def get_merchant(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Merchant:
    m = db.get(models.Merchant, merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return m


@router.patch("/merchants/{merchant_id}", response_model=MerchantOut)
def update_merchant(
    merchant_id: str,
    body: MerchantUpdate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Merchant:
    m = lock_live_merchant(db, merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    for k, v in body.model_dump(exclude_unset=True, exclude={"logo_base64"}).items():
        if v is None and k != "pass_logo_path":
            raise HTTPException(422, "Field cannot be null")
        setattr(m, k, v)
    if "logo_base64" in body.model_fields_set:
        m.logo_data = decode_logo(body.logo_base64) if body.logo_base64 is not None else None
        m.pass_logo_path = None
    db.commit()
    db.refresh(m)
    for customer in m.customers:
        passes.update_customer_pass(db, customer)
    return m


# ---------- Customers ----------
def deletion_summary(db: Session, merchant: models.Merchant) -> dict:
    customers = db.query(models.Customer).filter_by(merchant_id=merchant.id).all()
    customer_ids = [c.id for c in customers]
    groups = {
        "customers": customers,
        "campaigns": db.query(models.Campaign).filter_by(merchant_id=merchant.id).all(),
        "passes": db.query(models.Pass).filter(models.Pass.customer_id.in_(customer_ids)).all(),
        "coupons": db.query(models.Coupon).filter_by(merchant_id=merchant.id).all(),
        "admins": db.query(models.AdminUser).filter_by(merchant_id=merchant.id).all(),
        "transactions": db.query(models.Transaction).filter_by(merchant_id=merchant.id).all(),
        "movements": db.query(models.Movement)
        .filter(models.Movement.customer_id.in_(customer_ids))
        .all(),
    }
    snapshot = {key: sorted(row.id for row in rows) for key, rows in groups.items()}
    revision = hashlib.sha256(
        json.dumps([merchant.name, snapshot], sort_keys=True).encode()
    ).hexdigest()
    return {
        "name": merchant.name,
        "revision": revision,
        **{key: len(rows) for key, rows in groups.items()},
    }


class MerchantDeletion(BaseModel):
    revision: str


@router.get("/merchants/{merchant_id}/deletion-preview")
def preview_merchant_deletion(
    merchant_id: str, db: Session = Depends(get_db), user: models.AdminUser = Depends(super_admin)
) -> dict:
    merchant = db.get(models.Merchant, merchant_id)
    if not merchant or merchant.status == "deleted":
        raise HTTPException(404, "Merchant not found")
    return deletion_summary(db, merchant)


@router.delete("/merchants/{merchant_id}")
def delete_merchant(
    merchant_id: str,
    body: MerchantDeletion,
    db: Session = Depends(get_db),
    user: models.AdminUser = Depends(super_admin),
) -> dict:
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    merchant = db.get(models.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    summary = deletion_summary(db, merchant)
    if body.revision != summary["revision"]:
        raise HTTPException(
            409, "Merchant data changed. Refresh the deletion summary and confirm again."
        )
    merchant.status = "deleted"
    for customer in merchant.customers:
        customer.deleted = True
    for campaign in merchant.campaigns:
        campaign.deleted = True
        campaign.active = False
    db.query(models.Coupon).filter_by(merchant_id=merchant_id, status="issued").update(
        {"status": "cancelled"}
    )
    admins = db.query(models.AdminUser.id).filter_by(merchant_id=merchant_id)
    db.query(models.AdminSession).filter(models.AdminSession.user_id.in_(admins)).delete(
        synchronize_session=False
    )
    rows = (
        db.query(models.Pass)
        .join(models.Customer)
        .filter(models.Customer.merchant_id == merchant_id)
        .all()
    )
    passes.mark_revoked(db, rows)
    db.commit()
    pending = sum(not passes.revoke_pass(db, row.customer, row.id) for row in rows)
    return {"status": "deleted", "pending_revocations": pending, "summary": summary}


@router.post("/merchants/{merchant_id}/customers", response_model=dict)
def enroll_customer(
    merchant_id: str,
    body: CustomerCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> dict:
    lock_live_merchant(db, merchant_id)
    # Only validated HMAC-SHA256 digests are accepted, never raw PAN.
    card_hash = body.card_hash
    c = models.Customer(
        merchant_id=merchant_id,
        customer_code=body.customer_code,
        card_hash=card_hash,
        email=body.email,
        dni=body.dni,
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Customer code already exists")
    db.refresh(c)
    return {"customer": CustomerOut.model_validate(c).model_dump(), "pass_links": {}}


@router.get("/merchants/{merchant_id}/customers", response_model=list[CustomerOut])
def list_customers(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> list[models.Customer]:
    return db.query(models.Customer).filter_by(merchant_id=merchant_id, deleted=False).all()


# ---------- Campaigns ----------
@router.post("/merchants/{merchant_id}/campaigns", response_model=CampaignOut)
def create_campaign(
    merchant_id: str,
    body: CampaignCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Campaign:
    lock_live_merchant(db, merchant_id)
    if body.type not in ("points_per_spend", "interaction", "coupon"):
        raise HTTPException(400, "Invalid campaign type")
    camp = models.Campaign(merchant_id=merchant_id, **body.model_dump())
    db.add(camp)
    db.commit()
    db.refresh(camp)
    return camp


@router.get("/merchants/{merchant_id}/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> list[models.Campaign]:
    return db.query(models.Campaign).filter_by(merchant_id=merchant_id, deleted=False).all()


@router.delete("/merchants/{merchant_id}/campaigns/{campaign_id}")
def delete_campaign(
    merchant_id: str,
    campaign_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> dict:
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign or campaign.merchant_id != merchant_id:
        raise HTTPException(404, "Campaign not found")
    campaign.active = False
    campaign.deleted = True
    rows = db.query(models.Pass).filter_by(campaign_id=campaign_id).all()
    passes.mark_revoked(db, rows)
    db.commit()
    pending = sum(not passes.revoke_pass(db, row.customer, row.id) for row in rows)
    return {"status": "deleted", "pending_revocations": pending}


# ---------- Coupons ----------
@router.post("/merchants/{merchant_id}/coupons", response_model=CouponOut)
def issue_coupon(
    merchant_id: str,
    body: CouponCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Coupon:
    lock_live_merchant(db, merchant_id)
    customer = db.get(models.Customer, body.customer_id)
    if not customer or customer.deleted or customer.merchant_id != merchant_id:
        raise HTTPException(404, "Customer not found in merchant")
    coupon = models.Coupon(
        merchant_id=merchant_id, customer_id=body.customer_id, amount=body.amount
    )
    db.add(coupon)
    db.flush()
    db.add(
        models.Movement(
            customer_id=customer.id,
            type="coupon_issued",
            points_delta=0,
            description=f"Coupon {coupon.id}: {coupon.amount} EUR",
        )
    )
    db.commit()
    passes.update_customer_pass(db, customer)
    return coupon


@router.get("/merchants/{merchant_id}/coupons", response_model=list[CouponOut])
def list_coupons(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> list[models.Coupon]:
    return db.query(models.Coupon).filter(models.Coupon.merchant_id == merchant_id).all()
