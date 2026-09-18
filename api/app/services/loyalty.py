"""Atomic loyalty accrual, merchant-scoped matching and idempotent ingestion."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..schemas import TransactionIdentifiers, TransactionIn, TransactionResult
from . import passes


def match_customer(
    db: Session, merchant_id: str, ids: TransactionIdentifiers
) -> models.Customer | None:
    query = db.query(models.Customer).filter_by(merchant_id=merchant_id)
    for field, value in (
        ("card_hash", ids.card_hash),
        ("customer_code", ids.customer_number),
        ("email", ids.email),
        ("dni", ids.dni),
    ):
        if value:
            customer = query.filter(getattr(models.Customer, field) == value).first()
            if customer:
                return customer
    return None


def _points_for_spend(config: dict, amount: Decimal | float) -> int:
    amount = Decimal(str(amount))
    unit = Decimal(str(config.get("amount_unit", 10)))
    if amount <= 0 or unit <= 0:
        return 0
    raw = amount / unit * Decimal(str(config.get("points", 1)))
    rounding = {"floor": ROUND_FLOOR, "ceil": ROUND_CEILING, "round": ROUND_HALF_UP}[
        config.get("rounding", "floor")
    ]
    return int(raw.to_integral_value(rounding=rounding))


def _record_movement(
    db: Session,
    customer: models.Customer,
    mtype: str,
    delta: int,
    transaction_id: str | None,
    campaign_id: str | None = None,
    description: str | None = None,
) -> None:
    customer.points_balance += delta
    db.add(
        models.Movement(
            customer_id=customer.id,
            type=mtype,
            points_delta=delta,
            transaction_id=transaction_id,
            campaign_id=campaign_id,
            description=description,
        )
    )


def apply_campaigns(
    db: Session,
    merchant_id: str,
    customer: models.Customer,
    amount: Decimal | None,
    transaction_id: str,
) -> int:
    total = 0
    campaigns = db.query(models.Campaign).filter_by(merchant_id=merchant_id, active=True).all()
    for campaign in campaigns:
        if campaign.type == "points_per_spend" and amount:
            delta = _points_for_spend(campaign.config, amount)
            if delta:
                _record_movement(db, customer, "earn", delta, transaction_id, campaign.id)
                total += delta
        elif campaign.type == "interaction":
            count = (
                db.query(models.Movement)
                .filter_by(customer_id=customer.id, campaign_id=campaign.id, type="interaction")
                .count()
                + 1
            )
            _record_movement(
                db, customer, "interaction", 0, transaction_id, campaign.id, f"Stamp {count}"
            )
            if count % campaign.config["interactions_required"] == 0:
                _record_movement(
                    db,
                    customer,
                    "reward",
                    0,
                    transaction_id,
                    campaign.id,
                    campaign.config["reward_description"],
                )
    # Redeem whole coupons oldest first, bounded by this payment. No partial coupons.
    remaining = Decimal(str(amount or 0))
    for coupon in (
        db.query(models.Coupon)
        .filter_by(customer_id=customer.id, merchant_id=merchant_id, status="issued")
        .order_by(models.Coupon.issued_at, models.Coupon.id)
        .all()
    ):
        if coupon.amount <= remaining:
            coupon.status = "redeemed"
            coupon.redeemed_at = models._now()
            remaining -= coupon.amount
            _record_movement(
                db,
                customer,
                "coupon_redeemed",
                0,
                transaction_id,
                description=f"Coupon {coupon.id}: {coupon.amount} EUR",
            )
    return total


def ingest_transaction(db: Session, payload: TransactionIn) -> TransactionResult:
    # SQLite serializes writers before reading balances/idempotency keys, including
    # across API workers. This prevents duplicate accrual and lost balance updates.
    db.execute(text("BEGIN IMMEDIATE"))
    merchant = db.get(models.Merchant, payload.merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    existing = (
        db.query(models.Transaction)
        .filter_by(external_transaction_id=payload.external_transaction_id)
        .first()
    )
    if existing:
        if existing.merchant_id != payload.merchant_id:
            raise HTTPException(409, "External transaction ID already used")
        db.commit()
        return TransactionResult(status="duplicate", customer_id=existing.matched_customer_id)
    if merchant.status != "active":
        raise HTTPException(409, "Merchant is inactive")
    customer = match_customer(db, payload.merchant_id, payload.identifiers)
    txn = models.Transaction(
        merchant_id=payload.merchant_id,
        external_transaction_id=payload.external_transaction_id,
        source=payload.source,
        amount=payload.amount,
        **payload.identifiers.model_dump(),
        matched_customer_id=customer.id if customer else None,
        status="matched" if customer else "unmatched",
    )
    db.add(txn)
    db.flush()
    if not customer:
        db.commit()
        return TransactionResult(status="unmatched")
    delta = apply_campaigns(db, payload.merchant_id, customer, payload.amount, txn.id)
    db.commit()
    # External provider failures must never roll back a payment or duplicate points.
    updated = passes.update_customer_pass(db, customer)
    return TransactionResult(
        status="matched",
        customer_id=customer.id,
        points_delta=delta,
        new_balance=customer.points_balance,
        pass_updated=updated,
    )
