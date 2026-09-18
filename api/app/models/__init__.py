"""SQLAlchemy models for the SME Loyalty Platform (PRD §8).

Importing this package registers every model on Base.metadata.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
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
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False)
    customer_code: Mapped[str] = mapped_column(String, nullable=False)  # shown on pass / QR
    card_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # irreversible hash of PAN
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    dni: Mapped[str | None] = mapped_column(String, nullable=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    merchant = relationship("Merchant", back_populates="customers")
    passes = relationship("Pass", back_populates="customer", cascade="all, delete-orphan")
    movements = relationship("Movement", back_populates="customer", cascade="all, delete-orphan")


class Pass(Base):
    __tablename__ = "pass"
    __table_args__ = (UniqueConstraint("customer_id", "platform", name="uq_customer_platform"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # apple / google
    external_pass_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active / revoked
    auth_token: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_tag: Mapped[int] = mapped_column(Integer, default=0)
    synced_tag: Mapped[int] = mapped_column(Integer, default=0)
    pass_type_id: Mapped[str | None] = mapped_column(String, nullable=True)

    customer = relationship("Customer", back_populates="passes")


class Campaign(Base):
    __tablename__ = "campaign"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False)
    type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # points_per_spend / interaction / coupon
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    merchant = relationship("Merchant", back_populates="campaigns")


class Coupon(Base):
    __tablename__ = "coupon"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String, default="issued")  # issued / redeemed
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), nullable=False)
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


class DeviceRegistration(Base):
    __tablename__ = "device_registration"
    __table_args__ = (UniqueConstraint("device_id", "pass_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    pass_id: Mapped[str] = mapped_column(ForeignKey("pass.id"), nullable=False)
    push_token: Mapped[str] = mapped_column(String, nullable=False)
