"""Pydantic schemas for request/response validation."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..services.logos import decode_logo
from .notifications import NotificationContent


# ---------- Merchant ----------
class MerchantLogo(BaseModel):
    logo_base64: str | None = Field(default=None, max_length=2796204)

    @field_validator("logo_base64")
    @classmethod
    def validate_logo(cls, value: str | None) -> str | None:
        if value is not None:
            decode_logo(value)
        return value


class MerchantCreate(MerchantLogo):
    name: str = Field(min_length=1, max_length=200)
    pass_color: str = Field(default="#C81E1E", pattern=r"^#[0-9a-fA-F]{6}$")
    pass_logo_path: str | None = None


class MerchantUpdate(MerchantLogo):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "inactive"] | None = None
    pass_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    pass_logo_path: str | None = None


class MerchantOut(BaseModel):
    onboarding_status: str = "pending_campaign"
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str = Field(min_length=1, max_length=200)
    status: str
    pass_color: str
    pass_logo_path: str | None
    logo_url: str | None
    created_at: datetime


# ---------- Customer ----------
class CustomerCreate(BaseModel):
    joined_on: date | None = None

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: date | None) -> date | None:
        if value and value > datetime.now(timezone.utc).date():
            raise ValueError("Customer joining date cannot be in the future")
        return value

    name: str | None = Field(default=None, min_length=1, max_length=200)
    campaign_ids: list[str] = Field(default_factory=list, max_length=100)
    customer_code: str = Field(min_length=1, max_length=100)
    card_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )  # lowercase HMAC-SHA256 digest only
    email: str | None = None
    dni: str | None = None


class CustomerOut(BaseModel):
    name: str | None = None
    membership_status: str = "pending"
    legacy_points_balance: int = 0
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    customer_code: str = Field(min_length=1, max_length=100)
    email: str | None
    dni: str | None
    points_balance: int
    created_at: datetime


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    type: str
    points_delta: int
    transaction_id: str | None
    campaign_id: str | None = None
    description: str | None = None
    created_at: datetime


# ---------- Campaign ----------
class PassDesignIn(BaseModel):
    points_label: str | None = Field(default=None, min_length=1, max_length=80)
    member_since_label: str | None = Field(default=None, min_length=1, max_length=80)
    barcode_alternate_text: str | None = Field(default=None, min_length=1, max_length=200)
    logo_asset_id: str | None = None
    hero_asset_id: str | None = None
    background_color: str = Field(default="#373839", pattern=r"^#[0-9a-fA-F]{6}$")
    logo_description: str = Field(default="Campaign logo", min_length=1, max_length=200)
    hero_description: str = Field(default="Campaign image", min_length=1, max_length=200)
    subheader: str = Field(default="Cliente", min_length=1, max_length=100)
    locale: Literal["es-ES", "en-US"] = "es-ES"


class PassDesignOut(PassDesignIn):
    legacy_review_required: bool = False
    model_config = ConfigDict(from_attributes=True)
    logo_url: str | None = None
    hero_url: str | None = None


class CampaignCreate(BaseModel):
    description: str = Field(default="", max_length=2000)
    design: PassDesignIn | None = None
    customer_ids: list[str] = Field(default_factory=list, max_length=1000)
    lifecycle: Literal["draft", "ready"] | None = None
    name: str = Field(default="Campaign", min_length=1, max_length=200)
    type: Literal["points_per_spend", "interaction", "coupon"]
    config: dict
    active: bool = True

    @model_validator(mode="after")
    def validate_config(self) -> "CampaignCreate":
        kind = {
            "points_per_spend": PointsConfig,
            "interaction": InteractionConfig,
            "coupon": CouponConfig,
        }[self.type]
        self.config = kind.model_validate(self.config).model_dump()
        return self


class PointsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    points: int = Field(default=1, gt=0, le=1000000)
    amount_unit: float = Field(default=10, gt=0, allow_inf_nan=False)
    rounding: Literal["floor", "ceil", "round"] = "floor"


class InteractionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interactions_required: int = Field(gt=0)
    reward_description: str = Field(min_length=1, max_length=500)


class CouponConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: Literal["EUR"] = "EUR"


class CampaignOut(BaseModel):
    description: str = ""
    lifecycle: str = "draft"
    design: PassDesignOut | None = None
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    name: str
    type: str
    config: dict
    active: bool


class EnrollmentBatch(BaseModel):
    customer_ids: list[str] = Field(min_length=1, max_length=1000)


class EnrollmentOut(BaseModel):
    id: str
    campaign_id: str
    customer_id: str
    campaign_name: str
    customer_name: str
    customer_code: str
    status: Literal["active", "suspended", "cancelled"]
    enrolled_at: datetime
    created_at: datetime
    updated_at: datetime
    points_balance: int
    pending_revocations: int = 0


class PassAssetOut(BaseModel):
    id: str
    url: str
    content_type: str
    width: int
    height: int
    size: int


class EnrollmentUpdate(BaseModel):
    status: Literal["active", "suspended", "cancelled"]


class BarcodeVerification(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class PassAssignment(BaseModel):
    campaign_id: str
    platform: Literal["apple", "google"]


# ---------- Coupon ----------
class CouponCreate(BaseModel):
    customer_id: str
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    customer_id: str
    amount: float
    status: str


# ---------- Transaction ingestion ----------
class TransactionIdentifiers(BaseModel):
    card_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    customer_number: str | None = None
    email: str | None = None
    dni: str | None = None


class TransactionIn(BaseModel):
    merchant_id: str
    external_transaction_id: str = Field(min_length=1, max_length=200)
    source: Literal["getnet", "ecommerce", "other"] = "other"  # getnet / ecommerce / other
    amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    identifiers: TransactionIdentifiers = Field(default_factory=TransactionIdentifiers)
    send_notification: bool = False
    notification: NotificationContent | None = None

    @model_validator(mode="after")
    def notification_required(self) -> "TransactionIn":
        if self.send_notification and not self.notification:
            raise ValueError("Notification title and message are required when sending")
        return self


class TransactionResult(BaseModel):
    status: str  # matched / unmatched / duplicate
    customer_id: str | None = None
    points_delta: int = 0
    new_balance: int | None = None
    pass_updated: bool = False
    notification_id: str | None = None
    notification_status: str | None = None
