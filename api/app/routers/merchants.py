from fastapi import APIRouter, Depends, HTTPException
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
    query = db.query(models.Merchant)
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
    m = db.get(models.Merchant, merchant_id)
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
@router.post("/merchants/{merchant_id}/customers", response_model=dict)
def enroll_customer(
    merchant_id: str,
    body: CustomerCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> dict:
    if not db.get(models.Merchant, merchant_id):
        raise HTTPException(404, "Merchant not found")
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
    links = passes.issue_pass_links(db, c)
    db.commit()
    return {"customer": CustomerOut.model_validate(c).model_dump(), "pass_links": links}


@router.get("/merchants/{merchant_id}/customers", response_model=list[CustomerOut])
def list_customers(
    merchant_id: str,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> list[models.Customer]:
    return db.query(models.Customer).filter(models.Customer.merchant_id == merchant_id).all()


# ---------- Campaigns ----------
@router.post("/merchants/{merchant_id}/campaigns", response_model=CampaignOut)
def create_campaign(
    merchant_id: str,
    body: CampaignCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Campaign:
    if not db.get(models.Merchant, merchant_id):
        raise HTTPException(404, "Merchant not found")
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
    return db.query(models.Campaign).filter(models.Campaign.merchant_id == merchant_id).all()


# ---------- Coupons ----------
@router.post("/merchants/{merchant_id}/coupons", response_model=CouponOut)
def issue_coupon(
    merchant_id: str,
    body: CouponCreate,
    db: Session = Depends(get_db),
    merchant: models.Merchant = Depends(merchant_access),
) -> models.Coupon:
    if not db.get(models.Merchant, merchant_id):
        raise HTTPException(404, "Merchant not found")
    customer = db.get(models.Customer, body.customer_id)
    if not customer or customer.merchant_id != merchant_id:
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
