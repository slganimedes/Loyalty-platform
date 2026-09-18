from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import CustomerOut, MovementOut
from ..services import passes
from .auth import authorize_merchant, current_user

router = APIRouter(prefix="/api/v1", tags=["customers"])


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: str, db: Session = Depends(get_db), user: models.AdminUser = Depends(current_user)
) -> models.Customer:
    c = db.get(models.Customer, customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(c.merchant_id, user, db)
    return c


@router.get("/customers/{customer_id}/movements", response_model=list[MovementOut])
def get_movements(
    customer_id: str, db: Session = Depends(get_db), user: models.AdminUser = Depends(current_user)
) -> list[models.Movement]:
    c = db.get(models.Customer, customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(c.merchant_id, user, db)
    return (
        db.query(models.Movement)
        .filter(models.Movement.customer_id == customer_id)
        .order_by(models.Movement.created_at.desc())
        .all()
    )


@router.get("/customers/{customer_id}/passes", response_model=dict)
def get_passes(
    customer_id: str, db: Session = Depends(get_db), user: models.AdminUser = Depends(current_user)
) -> dict:
    c = db.get(models.Customer, customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(c.merchant_id, user, db)
    links = passes.issue_pass_links(db, c)
    db.commit()
    return {"pass_links": links}


@router.post("/customers/{customer_id}/passes/refresh")
def refresh_passes(
    customer_id: str, db: Session = Depends(get_db), user: models.AdminUser = Depends(current_user)
) -> dict:
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    authorize_merchant(customer.merchant_id, user, db)
    updated = passes.update_customer_pass(db, customer)
    return {"pass_updated": updated, "pass_links": passes.issue_pass_links(db, customer)}
