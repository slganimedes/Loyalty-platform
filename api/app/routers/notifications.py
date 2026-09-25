"""Notifications use the same tenant/session rules as other business endpoints."""

from datetime import date, datetime, time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..schemas.notifications import NotificationDraft, NotificationSend, NotificationStatus
from ..services import notifications as service
from .auth import authorize_merchant, current_user

router = APIRouter(prefix="/api/v1/merchants/{merchant_id}", tags=["notifications"])


@router.get("/notification-campaigns")
def campaigns(
    merchant_id: str, db: Session = Depends(get_db), user: m.AdminUser = Depends(current_user)
) -> list[dict]:
    authorize_merchant(merchant_id, user, db)
    result = []
    for campaign in (
        db.query(m.Campaign)
        .filter_by(merchant_id=merchant_id, deleted=False)
        .order_by(m.Campaign.name)
        .all()
    ):
        rows = (
            service.eligible_passes(db, merchant_id).filter(m.Pass.campaign_id == campaign.id).all()
        )
        result.append(
            {
                "id": campaign.id,
                "name": campaign.name,
                "type": campaign.type,
                "config": campaign.config,
                "pass_count": len(rows),
                "estimated_recipients": len({r.customer_id for r in rows}),
            }
        )
    return result


@router.get("/notification-passes")
def search_passes(
    merchant_id: str,
    q: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    query = service.eligible_passes(db, merchant_id)
    if q.strip():
        # Escaped literal matching, including QR enrollment tokens and legacy identifiers.
        columns = [
            m.Customer.name,
            m.Customer.email,
            m.Customer.customer_code,
            m.Pass.id,
            m.Pass.external_pass_id,
            m.CampaignEnrollment.barcode_token,
        ]
        query = query.filter(or_(*(c.icontains(q.strip(), autoescape=True) for c in columns)))
    return {
        "total": query.count(),
        "items": [
            service.pass_summary(db, r)
            for r in query.order_by(m.Customer.name, m.Pass.id).offset(offset).limit(30).all()
        ],
    }


@router.post("/notifications/preview")
def preview(
    merchant_id: str,
    body: NotificationDraft,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    return service.preview(db, merchant_id, body)


@router.post("/notifications", status_code=202)
def send(
    merchant_id: str,
    body: NotificationSend,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    row = service.NotificationService(db, merchant_id, user).send(body)
    result = service.history_item(db, row)
    background.add_task(service.dispatch_pending)
    return result


@router.get("/notifications")
def history(
    merchant_id: str,
    campaign_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: NotificationStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Start date must be on or before end date")
    query = db.query(m.Notification).filter_by(merchant_id=merchant_id)
    if campaign_id:
        # Payment notifications may span several campaigns.
        query = query.filter(
            or_(
                m.Notification.campaign_id == campaign_id,
                m.Notification.id.in_(
                    db.query(m.NotificationDelivery.notification_id)
                    .join(m.Pass)
                    .filter(m.Pass.campaign_id == campaign_id)
                ),
            )
        )
    if date_from:
        query = query.filter(m.Notification.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(m.Notification.created_at <= datetime.combine(date_to, time.max))
    if status:
        query = query.filter_by(status=status)
    return {
        "total": query.count(),
        "items": [
            service.history_item(db, row)
            for row in query.order_by(m.Notification.created_at.desc(), m.Notification.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        ],
    }


@router.get("/notifications/{notification_id}")
def detail(
    merchant_id: str,
    notification_id: str,
    db: Session = Depends(get_db),
    user: m.AdminUser = Depends(current_user),
) -> dict:
    authorize_merchant(merchant_id, user, db)
    row = db.get(m.Notification, notification_id)
    if not row or row.merchant_id != merchant_id:
        raise HTTPException(404, "Notification not found")
    return service.history_item(db, row, details=True)
