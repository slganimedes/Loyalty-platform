"""Shared composer contract, including safe, explicit template substitutions."""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NotificationType = Literal[
    "general_update", "new_reward", "points_earned", "coupon_available", "coupon_expiring", "custom"
]
NotificationStatus = Literal[
    "queued", "sending", "success", "partial", "failed", "skipped", "unknown"
]
PLACEHOLDERS = (
    "customerName",
    "campaignName",
    "amount",
    "pointsEarned",
    "currentPoints",
    "currentStamps",
    "rewardName",
)
TOKEN = re.compile(r"\{\{\s*([A-Za-z]+)\s*\}\}")


class NotificationContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)
    url: str | None = Field(default=None, max_length=2048)
    preview_text: str = Field(default="", max_length=200)
    type: NotificationType = "general_update"

    @field_validator("title", "message", "preview_text")
    @classmethod
    def valid_template(cls, value: str) -> str:
        tokens = TOKEN.findall(value)
        remainder = TOKEN.sub("", value)
        if (
            any(token not in PLACEHOLDERS for token in tokens)
            or "{{" in remainder
            or "}}" in remainder
        ):
            raise ValueError("Unknown or malformed placeholder")
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Control characters are not allowed")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in ("https", "http")
                and url.hostname
                and not url.username
                and not url.password
                and not any(c.isspace() or ord(c) < 32 for c in value)
                and "{{" not in value
                and "\\" not in value
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use a complete http:// or https:// link without credentials")
        return value


class NotificationDraft(NotificationContent):
    target_type: Literal["campaign", "pass"]
    campaign_id: str | None = Field(default=None, max_length=100)
    pass_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def one_target(self) -> "NotificationDraft":
        if self.target_type == "campaign" and (not self.campaign_id or self.pass_id):
            raise ValueError("Select one campaign")
        if self.target_type == "pass" and (not self.pass_id or self.campaign_id):
            raise ValueError("Select one pass")
        for value in (self.title, self.message, self.preview_text):
            if set(TOKEN.findall(value)) & {"amount", "pointsEarned"}:
                raise ValueError(
                    "amount and pointsEarned are available only for payment notifications"
                )
        return self


class NotificationSend(NotificationDraft):
    request_id: str = Field(min_length=8, max_length=100)
    expected_recipients: int = Field(ge=1)
    audience_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_mass_send: bool = False
