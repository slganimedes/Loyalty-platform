"""Pydantic schemas for request/response validation."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..services.logos import decode_logo


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
    customer_code: str = Field(min_length=1, max_length=100)
    card_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )  # lowercase HMAC-SHA256 digest only
    email: str | None = None
    dni: str | None = None


class CustomerOut(BaseModel):
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
class CampaignCreate(BaseModel):
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
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    name: str
    type: str
    config: dict
    active: bool


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


class TransactionResult(BaseModel):
    status: str  # matched / unmatched / duplicate
    customer_id: str | None = None
    points_delta: int = 0
    new_balance: int | None = None
    pass_updated: bool = False
