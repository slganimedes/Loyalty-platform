"""SQLAlchemy models for the SME Loyalty Platform (PRD §8).

Importing this package registers every model on Base.metadata.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Merchant(Base):
    __tablename__ = "merchant"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")  # active / inactive
    pass_color: Mapped[str] = mapped_column(String, default="#C81E1E")
    pass_logo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    customers = relationship("Customer", back_populates="merchant", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="merchant", cascade="all, delete-orphan")

    @property
    def onboarding_status(self) -> str:
        return (
            "ready"
            if any(not c.deleted and c.lifecycle != "draft" for c in self.campaigns)
            else "pending_campaign"
        )

    @property
    def logo_url(self) -> str | None:
        if self.logo_data:
            version = hashlib.sha256(self.logo_data).hexdigest()[:16]
            return f"/api/v1/wallet/merchants/{self.id}/logo.png?v={version}"
        if self.pass_logo_path:
            return f"/api/v1/wallet/merchants/{self.id}/logo.png"
        return None


class AdminUser(Base):
    __tablename__ = "admin_user"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # super_admin / sme_admin
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey("merchant.id"), nullable=True)
    language: Mapped[str] = mapped_column(String, default="es")  # es / en


class WalletConfig(Base):
    """Platform-level wallet provider settings (single row for the pilot)."""

    __tablename__ = "wallet_config"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    apple_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    apple_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    google_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    google_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = (
        UniqueConstraint("merchant_id", "customer_code", name="uq_customer_per_merchant"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String, nullable=False)  # shown on pass / QR
    card_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # irreversible hash of PAN
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    dni: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    legacy_points_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    @property
    def membership_status(self) -> str:
        from sqlalchemy.orm import object_session

        db = object_session(self)
        if (
            db
            and db.query(CampaignEnrollment).filter_by(customer_id=self.id, status="active").first()
        ):
            return "active"
        return "pending"

    merchant = relationship("Merchant", back_populates="customers")
    passes = relationship("Pass", back_populates="customer", cascade="all, delete-orphan")
    movements = relationship("Movement", back_populates="customer", cascade="all, delete-orphan")


class Pass(Base):
    __tablename__ = "pass"
    __table_args__ = (
        Index(
            "uq_active_campaign_pass",
            "customer_id",
            "campaign_id",
            "platform",
            unique=True,
            sqlite_where=text("status = 'active' AND campaign_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaign.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # apple / google
    external_pass_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active / revoked
    auth_token: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_tag: Mapped[int] = mapped_column(Integer, default=0)
    synced_tag: Mapped[int] = mapped_column(Integer, default=0)
    pass_type_id: Mapped[str | None] = mapped_column(String, nullable=True)
    google_kind: Mapped[str] = mapped_column(String, default="loyalty", nullable=False)
    enrollment_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaign_enrollment.id"), nullable=True, index=True
    )
    enrollment = relationship("CampaignEnrollment")

    customer = relationship("Customer", back_populates="passes")
    campaign = relationship("Campaign")


class Campaign(Base):
    __tablename__ = "campaign"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, default="Campaign", nullable=False)
    type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # points_per_spend / interaction / coupon
    description: Mapped[str] = mapped_column(String, default="", nullable=False)
    lifecycle: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    merchant = relationship("Merchant", back_populates="campaigns")
    design = relationship("PassDesign", uselist=False, back_populates="campaign")


class Coupon(Base):
    __tablename__ = "coupon"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String, default="issued")  # issued / redeemed
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False, index=True)
    external_transaction_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String, default="other")  # getnet / ecommerce / other
    amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    card_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    dni: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_number: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="unmatched")  # matched / unmatched
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Movement(Base):
    """Functional traceability of every balance change."""

    __tablename__ = "movement"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # earn / redeem / interaction / coupon
    points_delta: Mapped[int] = mapped_column(Integer, default=0)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transaction.id"), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaign.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    customer = relationship("Customer", back_populates="movements")


class AdminSession(Base):
    __tablename__ = "admin_session"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_user.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Notification(Base):
    """Immutable audience/content snapshot and durable notification outbox."""

    __tablename__ = "notification"
    __table_args__ = (UniqueConstraint("merchant_id", "request_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), index=True)
    request_id: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    sender_id: Mapped[str | None] = mapped_column(ForeignKey("admin_user.id"), nullable=True)
    sender_name: Mapped[str] = mapped_column(String)
    target_type: Mapped[str] = mapped_column(String)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaign.id"), nullable=True)
    campaign_name: Mapped[str | None] = mapped_column(String, nullable=True)
    pass_id: Mapped[str | None] = mapped_column(ForeignKey("pass.id"), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transaction.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    estimated_recipients: Mapped[int] = mapped_column(Integer)
    pass_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_delivery"
    __table_args__ = (UniqueConstraint("notification_id", "pass_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notification.id"), index=True)
    pass_id: Mapped[str] = mapped_column(ForeignKey("pass.id"), index=True)
    platform: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PassNotificationState(Base):
    """Latest Apple back-of-pass message, retained across ordinary balance updates."""

    __tablename__ = "pass_notification_state"
    pass_id: Mapped[str] = mapped_column(ForeignKey("pass.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class DeviceRegistration(Base):
    __tablename__ = "device_registration"
    __table_args__ = (UniqueConstraint("device_id", "pass_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    pass_id: Mapped[str] = mapped_column(ForeignKey("pass.id"), nullable=False)
    push_token: Mapped[str] = mapped_column(String, nullable=False)


class CampaignEnrollment(Base):
    __tablename__ = "campaign_enrollment"
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id", name="uq_campaign_customer"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'cancelled')", name="ck_enrollment_status"
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    barcode_token: Mapped[str] = mapped_column(
        String, default=lambda: secrets.token_urlsafe(32), unique=True, nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )
    campaign = relationship("Campaign")
    customer = relationship("Customer")


class PassAsset(Base):
    __tablename__ = "pass_asset"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False, index=True)
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaign.id"), nullable=True, index=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    content_type: Mapped[str] = mapped_column(String, default="image/png", nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class PassDesign(Base):
    __tablename__ = "pass_design"
    points_label: Mapped[str | None] = mapped_column(String, nullable=True)
    member_since_label: Mapped[str | None] = mapped_column(String, nullable=True)
    barcode_alternate_text: Mapped[str | None] = mapped_column(String, nullable=True)
    legacy_review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id"), primary_key=True)
    logo_asset_id: Mapped[str | None] = mapped_column(ForeignKey("pass_asset.id"), nullable=True)
    hero_asset_id: Mapped[str | None] = mapped_column(ForeignKey("pass_asset.id"), nullable=True)
    background_color: Mapped[str] = mapped_column(String, default="#373839", nullable=False)
    logo_description: Mapped[str] = mapped_column(String, default="Campaign logo", nullable=False)
    hero_description: Mapped[str] = mapped_column(String, default="Campaign image", nullable=False)
    subheader: Mapped[str] = mapped_column(String, default="Cliente", nullable=False)
    locale: Mapped[str] = mapped_column(String, default="es-ES", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )
    campaign = relationship("Campaign", back_populates="design")

    @property
    def logo_url(self) -> str | None:
        from ..services.pass_assets import public_url

        return public_url(self.logo_asset_id) if self.logo_asset_id else None

    @property
    def hero_url(self) -> str | None:
        from ..services.pass_assets import public_url

        return public_url(self.hero_asset_id) if self.hero_asset_id else None


class SchemaMigration(Base):
    __tablename__ = "schema_migration"
    version: Mapped[str] = mapped_column(String, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
