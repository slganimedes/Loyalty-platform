"""Tenant-scoped notification planning, atomic rate reservations and durable delivery."""

import hashlib
import json
import logging
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Query, Session, aliased

from .. import models as m
from ..config import settings
from ..db import SessionLocal
from ..schemas.notifications import TOKEN, NotificationContent, NotificationDraft, NotificationSend
from . import passes
from .notification_providers import PROVIDERS

logger = logging.getLogger("notifications")
ACTIVE = ("pending", "sending", "success", "unknown")


def eligible_passes(db: Session, merchant_id: str) -> Query:
    return (
        db.query(m.Pass)
        .join(m.Customer)
        .outerjoin(m.Campaign, m.Pass.campaign_id == m.Campaign.id)
        .outerjoin(m.CampaignEnrollment, m.Pass.enrollment_id == m.CampaignEnrollment.id)
        .filter(
            m.Customer.merchant_id == merchant_id,
            m.Customer.deleted.is_(False),
            m.Pass.status == "active",
            m.Pass.platform.in_(["apple", "google"]),
            or_(
                m.Pass.campaign_id.is_(None),
                (m.Campaign.deleted.is_(False) & m.Campaign.active.is_(True)),
            ),
            or_(m.Pass.enrollment_id.is_(None), m.CampaignEnrollment.status == "active"),
        )
    )


def audience(db: Session, merchant_id: str, body: NotificationDraft) -> list[m.Pass]:
    query = eligible_passes(db, merchant_id)
    if body.target_type == "campaign":
        campaign = db.get(m.Campaign, body.campaign_id)
        if not campaign or campaign.merchant_id != merchant_id or campaign.deleted:
            raise HTTPException(404, "Campaign not found")
        query = query.filter(m.Pass.campaign_id == campaign.id)
    else:
        query = query.filter(m.Pass.id == body.pass_id)
    rows = query.order_by(m.Pass.id).limit(settings.notification_max_passes + 1).all()
    if body.target_type == "pass" and not rows:
        raise HTTPException(404, "Active pass not found")
    if len(rows) > settings.notification_max_passes:
        raise HTTPException(422, "Audience exceeds the configured maximum number of passes")
    return rows


def audience_revision(rows: list[m.Pass]) -> str:
    return hashlib.sha256("\n".join(sorted(row.id for row in rows)).encode()).hexdigest()


def template_context(db: Session, row: m.Pass, payment: dict | None = None) -> dict:
    campaign = row.campaign
    movements = db.query(m.Movement).filter_by(customer_id=row.customer_id)
    if campaign:
        movements = movements.filter_by(campaign_id=campaign.id)
    points = (
        int(movements.with_entities(func.coalesce(func.sum(m.Movement.points_delta), 0)).scalar())
        if campaign
        else row.customer.points_balance
    )
    stamps = movements.filter_by(type="interaction").count()
    context = {
        "customerName": row.customer.name or row.customer.customer_code,
        "campaignName": campaign.name if campaign else row.customer.merchant.name,
        "currentPoints": points,
        "currentStamps": stamps,
        "rewardName": (campaign.config.get("reward_description", "") if campaign else ""),
    }
    if payment:
        context.update(payment)
        # Earnings and balance are scoped to this pass's campaign, including multiple campaigns.
        earnings = movements.filter_by(transaction_id=payment["transaction_id"], type="earn")
        context["pointsEarned"] = int(
            earnings.with_entities(func.coalesce(func.sum(m.Movement.points_delta), 0)).scalar()
        )
    return context


def pass_summary(db: Session, row: m.Pass) -> dict:
    context = template_context(db, row)
    required = row.campaign.config.get("interactions_required", 0) if row.campaign else 0
    reward_count = (
        db.query(m.Movement)
        .filter_by(customer_id=row.customer_id, campaign_id=row.campaign_id, type="reward")
        .count()
    )
    return {
        "id": row.id,
        "platform": row.platform,
        "campaign_id": row.campaign_id,
        "campaign_name": context["campaignName"],
        "customer_name": context["customerName"],
        "email": row.customer.email,
        "customer_code": row.customer.customer_code,
        "campaign_type": row.campaign.type if row.campaign else "points_per_spend",
        "points_balance": context["currentPoints"],
        "stamp_count": context["currentStamps"],
        "reward_name": context["rewardName"],
        "rewards_earned": reward_count,
        "stamps_remaining": required - context["currentStamps"] % required if required else None,
        "context": context,
    }


def render(content: NotificationContent, context: dict) -> dict:
    result = content.model_dump(include={"title", "message", "url", "type", "preview_text"})
    for field in ("title", "message", "preview_text"):

        def substitute(match) -> str:
            if match[1] not in context:
                raise HTTPException(422, f"No value available for {match[1]}")
            return str(context[match[1]])

        result[field] = TOKEN.sub(substitute, result[field])
    if (
        not result["title"].strip()
        or not result["message"].strip()
        or len(result["title"]) > 200
        or len(result["message"]) > 2000
        or len(result["preview_text"]) > 200
    ):
        raise HTTPException(422, "Personalized content is empty or exceeds the maximum length")
    return result


def preview(db: Session, merchant_id: str, body: NotificationDraft) -> dict:
    rows = audience(db, merchant_id, body)
    rendered = [render(body, template_context(db, row)) for row in rows]
    count = len({row.customer_id for row in rows})
    warnings = []
    if not rows:
        warnings.append("no_passes")
    if count > settings.notification_mass_threshold:
        warnings.append("mass_send")
    if any(len(p["title"]) > 60 or len(p["message"]) > 240 for p in rendered):
        warnings.append("long_message")
    return {
        "estimated_recipients": count,
        "pass_count": len(rows),
        "audience_revision": audience_revision(rows),
        "mass_threshold": settings.notification_mass_threshold,
        "warnings": warnings,
        "sample": rendered[0] if rendered else body.model_dump(),
        "sample_pass": pass_summary(db, rows[0]) if rows else None,
    }


def history_item(db: Session, row: m.Notification, details: bool = False) -> dict:
    counts = dict(
        db.query(m.NotificationDelivery.status, func.count())
        .filter_by(notification_id=row.id)
        .group_by(m.NotificationDelivery.status)
        .all()
    )
    result = {
        "id": row.id,
        "created_at": row.created_at.isoformat() + "Z",
        "sender_id": row.sender_id,
        "sender_name": row.sender_name,
        "target_type": row.target_type,
        "campaign_id": row.campaign_id,
        "campaign_name": row.campaign_name,
        "pass_id": row.pass_id,
        "transaction_id": row.transaction_id,
        **row.payload,
        "estimated_recipients": row.estimated_recipients,
        "pass_count": row.pass_count,
        "status": row.status,
        "reason": row.reason,
        "delivery_counts": counts,
    }
    if details:
        result["deliveries"] = [
            {
                "pass_id": d.pass_id,
                "platform": d.platform,
                "status": d.status,
                "reason": d.reason,
                "payload": d.payload,
            }
            for d in db.query(m.NotificationDelivery).filter_by(notification_id=row.id).all()
        ]
    return result


def _rate_reason(db: Session, merchant_id: str, count: int) -> str | None:
    recent = db.query(m.Notification).filter(
        m.Notification.merchant_id == merchant_id,
        m.Notification.created_at > m._now() - timedelta(hours=1),
    )
    if recent.count() >= settings.notification_sends_per_hour:
        return "hourly_send_limit"
    total = recent.with_entities(func.coalesce(func.sum(m.Notification.pass_count), 0)).scalar()
    if total + count > settings.notification_passes_per_hour:
        return "hourly_recipient_limit"
    return None


class NotificationService:
    def __init__(self, db: Session, merchant_id: str, user: m.AdminUser) -> None:
        self.db, self.merchant_id, self.user = db, merchant_id, user

    def sendToPass(
        self, passId: str, title: str, message: str, url: str | None, type: str, **confirmation
    ) -> m.Notification:
        return self.send(
            NotificationSend(
                target_type="pass",
                pass_id=passId,
                title=title,
                message=message,
                url=url,
                type=type,
                **confirmation,
            )
        )

    def sendToCampaign(
        self, campaignId: str, title: str, message: str, url: str | None, type: str, **confirmation
    ) -> m.Notification:
        return self.send(
            NotificationSend(
                target_type="campaign",
                campaign_id=campaignId,
                title=title,
                message=message,
                url=url,
                type=type,
                **confirmation,
            )
        )

    def send(self, body: NotificationSend) -> m.Notification:
        db = self.db
        # Serialize idempotency, audience checks and quota reservations across API workers.
        db.execute(text("BEGIN IMMEDIATE"))
        fingerprint = hashlib.sha256(
            json.dumps(body.model_dump(exclude={"request_id"}), sort_keys=True).encode()
        ).hexdigest()
        existing = (
            db.query(m.Notification)
            .filter_by(merchant_id=self.merchant_id, request_id=body.request_id)
            .first()
        )
        if existing:
            if existing.request_hash != fingerprint:
                raise HTTPException(409, "Request ID already used for different content")
            db.commit()
            return existing
        merchant = db.get(m.Merchant, self.merchant_id)
        if merchant.status != "active":
            raise HTTPException(409, "Merchant is inactive")
        rows = audience(db, self.merchant_id, body)
        count = len({r.customer_id for r in rows})
        if not rows:
            raise HTTPException(422, "The selected campaign has no active passes")
        if body.expected_recipients != count or body.audience_revision != audience_revision(rows):
            raise HTTPException(409, "Recipients changed. Review the preview and confirm again")
        if count > settings.notification_mass_threshold and not body.confirm_mass_send:
            raise HTTPException(422, "Confirm the large audience before sending")
        reason = _rate_reason(db, self.merchant_id, len(rows))
        if reason:
            raise HTTPException(429, reason, headers={"Retry-After": "3600"})
        row = self.enqueue(
            rows,
            body,
            body.target_type,
            body.request_id,
            fingerprint,
            campaign_id=body.campaign_id or rows[0].campaign_id,
            pass_id=body.pass_id,
        )
        db.commit()
        return row

    def enqueue(
        self,
        rows: list[m.Pass],
        content: NotificationContent,
        target_type: str,
        request_id: str,
        fingerprint: str,
        campaign_id: str | None = None,
        pass_id: str | None = None,
        payment: dict | None = None,
        reason: str | None = None,
    ) -> m.Notification:
        """Called inside the payment transaction or send lock; never commits."""
        db = self.db
        campaign = db.get(m.Campaign, campaign_id) if campaign_id else None
        row = m.Notification(
            merchant_id=self.merchant_id,
            request_id=request_id,
            request_hash=fingerprint,
            sender_id=None if getattr(self.user, "public_access", False) else self.user.id,
            sender_name=self.user.username,
            target_type=target_type,
            campaign_id=campaign_id,
            campaign_name=campaign.name if campaign else None,
            pass_id=pass_id,
            transaction_id=payment["transaction_id"] if payment else None,
            payload=content.model_dump(include={"title", "message", "url", "type", "preview_text"}),
            estimated_recipients=len({p.customer_id for p in rows}),
            pass_count=len(rows),
            status="queued" if rows and not reason else "skipped",
            reason=reason or ("no_passes" if not rows else None),
        )
        db.add(row)
        db.flush()
        for target in rows:
            attempts = (
                db.query(m.NotificationDelivery)
                .filter(
                    m.NotificationDelivery.pass_id == target.id,
                    m.NotificationDelivery.status.in_(ACTIVE),
                    or_(
                        m.NotificationDelivery.status == "pending",
                        m.NotificationDelivery.created_at > m._now() - timedelta(hours=24),
                        m.NotificationDelivery.attempted_at > m._now() - timedelta(hours=24),
                    ),
                )
                .count()
            )
            skip = reason or (
                "daily_pass_limit" if attempts >= settings.notification_passes_per_day else None
            )
            try:
                payload = render(content, template_context(db, target, payment))
            except HTTPException:
                if not payment:
                    raise
                payload, skip = row.payload, "invalid_personalized_content"
            db.add(
                m.NotificationDelivery(
                    notification_id=row.id,
                    pass_id=target.id,
                    platform=target.platform,
                    payload=payload,
                    status="skipped" if skip else "pending",
                    reason=skip,
                )
            )
        db.flush()
        _summarize(db, row.id)
        logger.info(
            "Notification recorded id=%s sender=%s recipients=%d",
            row.id,
            row.sender_name,
            row.estimated_recipients,
        )
        return row


def enqueue_payment(
    db: Session, user: m.AdminUser, txn: m.Transaction, content: NotificationContent
) -> m.Notification:
    rows = (
        eligible_passes(db, txn.merchant_id)
        .filter(m.Pass.customer_id == txn.matched_customer_id)
        .all()
        if txn.matched_customer_id
        else []
    )
    reason = _rate_reason(db, txn.merchant_id, len(rows))
    return NotificationService(db, txn.merchant_id, user).enqueue(
        rows,
        content,
        "payment",
        f"payment:{txn.id}",
        txn.id,
        payment={"transaction_id": txn.id, "amount": f"{txn.amount or 0:.2f}"},
        reason=reason,
    )


def _summarize(db: Session, notification_id: str) -> None:
    row = db.get(m.Notification, notification_id)
    states = {
        s
        for (s,) in db.query(m.NotificationDelivery.status)
        .filter_by(notification_id=notification_id)
        .all()
    }
    if "sending" in states:
        row.status = "sending"
    elif "pending" in states:
        row.status = "queued"
    elif states == {"success"}:
        row.status = "success"
    elif "success" in states:
        row.status = "partial"
    elif "unknown" in states:
        row.status = "unknown"
    elif "failed" in states:
        row.status = "failed"
    else:
        row.status = "skipped"


def dispatch_pending(limit: int = 50) -> None:
    """Resume unattempted deliveries. Never replay a potentially accepted provider call."""
    for _ in range(limit):
        with SessionLocal() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            stale = (
                db.query(m.NotificationDelivery)
                .filter(
                    m.NotificationDelivery.status == "sending",
                    m.NotificationDelivery.attempted_at < m._now() - timedelta(minutes=10),
                )
                .all()
            )
            for item in stale:
                item.status, item.reason, item.completed_at = (
                    "unknown",
                    "delivery_uncertain",
                    m._now(),
                )
            db.flush()
            for notification_id in {item.notification_id for item in stale}:
                _summarize(db, notification_id)
            other = aliased(m.NotificationDelivery)
            busy = (
                db.query(other.id)
                .filter(other.pass_id == m.NotificationDelivery.pass_id, other.status == "sending")
                .exists()
            )
            delivery = (
                db.query(m.NotificationDelivery)
                .filter(m.NotificationDelivery.status == "pending", ~busy)
                .order_by(m.NotificationDelivery.created_at, m.NotificationDelivery.id)
                .first()
            )
            if not delivery:
                db.commit()
                return
            recent_attempts = (
                db.query(m.NotificationDelivery)
                .filter(
                    m.NotificationDelivery.pass_id == delivery.pass_id,
                    m.NotificationDelivery.status.in_(["sending", "success", "unknown"]),
                    m.NotificationDelivery.attempted_at > m._now() - timedelta(hours=24),
                )
                .count()
            )
            if recent_attempts >= settings.notification_passes_per_day:
                delivery.status, delivery.reason, delivery.completed_at = (
                    "skipped",
                    "daily_pass_limit",
                    m._now(),
                )
                db.flush()
                _summarize(db, delivery.notification_id)
                db.commit()
                continue
            delivery.status, delivery.attempted_at = "sending", m._now()
            db.get(m.Notification, delivery.notification_id).status = "sending"
            db.commit()  # Durable claim before any network request.
            delivery_id, notification_id = delivery.id, delivery.notification_id
            try:
                row = db.get(m.Pass, delivery.pass_id)
                merchant = row.customer.merchant
                if (
                    merchant.status != "active"
                    or not eligible_passes(db, merchant.id).filter(m.Pass.id == row.id).first()
                ):
                    status, reason = "skipped", "pass_inactive"
                else:
                    cfg = passes._wallet_config(db)
                    if not cfg or not getattr(cfg, f"{row.platform}_enabled"):
                        status, reason = "skipped", "provider_disabled"
                    else:
                        notification = db.get(m.Notification, notification_id)
                        if notification.transaction_id:
                            passes.update_customer_pass(db, row.customer)
                        status, reason = PROVIDERS[row.platform].send(
                            db, row, delivery, passes.provider_config(cfg, row.platform)
                        )
            except (httpx.TimeoutException, httpx.NetworkError):
                db.rollback()
                status, reason = "unknown", "delivery_uncertain"
            except Exception as exc:
                db.rollback()
                # Do not persist exception text: provider errors may contain credentials or URLs.
                logger.warning(
                    "Notification attempt id=%s kind=%s", delivery_id, type(exc).__name__
                )
                status, reason = "failed", "provider_error"
            # Serialize summary writes with enqueues and other delivery completions.
            db.commit()
            db.execute(text("BEGIN IMMEDIATE"))
            delivery = db.get(m.NotificationDelivery, delivery_id)
            delivery.status, delivery.reason, delivery.completed_at = status, reason, m._now()
            db.flush()
            _summarize(db, notification_id)
            db.commit()
