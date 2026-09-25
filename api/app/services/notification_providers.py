"""Wallet-specific delivery. Acceptance is never a receipt from a customer's device."""

from html import escape
from typing import Protocol

import httpx
from google.auth.transport.requests import Request
from sqlalchemy.orm import Session

from .. import models as m
from . import passes


class NotificationProvider(Protocol):
    def send(
        self, db: Session, row: m.Pass, delivery: m.NotificationDelivery, config: dict
    ) -> tuple[str, str | None]: ...


class AppleWalletNotificationProvider:
    def send(
        self, db: Session, row: m.Pass, delivery: m.NotificationDelivery, config: dict
    ) -> tuple[str, str | None]:
        state = db.get(m.PassNotificationState, row.id)
        if state is None:
            state = m.PassNotificationState(pass_id=row.id)
            db.add(state)
        state.payload = delivery.payload
        row.updated_tag = passes._next_tag(db)
        db.flush()
        # Validate signing before publishing a new version; devices must see committed data.
        passes.apple_bundle(db, row.customer, row, config)
        db.commit()
        if not db.query(m.DeviceRegistration).filter_by(pass_id=row.id).first():
            return "skipped", "no_registered_device"
        accepted = passes.push_apple(db, row, config)
        if not accepted:
            return "failed", "provider_rejected"
        if not db.query(m.DeviceRegistration).filter_by(pass_id=row.id).first():
            return "skipped", "no_registered_device"
        return "success", None


class GoogleWalletNotificationProvider:
    def send(
        self, db: Session, row: m.Pass, delivery: m.NotificationDelivery, config: dict
    ) -> tuple[str, str | None]:
        if not row.external_pass_id:
            return "skipped", "pass_not_issued"
        credentials = passes._google_credentials(config)
        credentials.refresh(Request())
        payload = delivery.payload
        # Google supports links in message bodies. Escape all merchant/customer text.
        body = escape(payload["message"])
        if payload.get("preview_text"):
            body += "\n" + escape(payload["preview_text"])
        if payload.get("url"):
            url = escape(payload["url"], quote=True)
            body += f'\n<a href="{url}">{url}</a>'
        endpoint = f"{passes.GOOGLE_BASE}/{row.google_kind}Object/{row.external_pass_id}"
        with httpx.Client(
            timeout=15, headers={"Authorization": f"Bearer {credentials.token}"}
        ) as client:
            current = client.get(endpoint)
            if not current.is_success:
                return "failed", "provider_rejected"
            messages = current.json().get("messages", [])
            if len(messages) >= 10:
                # Retire only this service's oldest messages. The audit keeps all content.
                owned = (
                    db.query(m.NotificationDelivery.id)
                    .filter_by(pass_id=row.id)
                    .order_by(m.NotificationDelivery.created_at)
                    .all()
                )
                for (message_id,) in owned:
                    if len(messages) < 10:
                        break
                    messages = [message for message in messages if message.get("id") != message_id]
                if len(messages) >= 10:
                    return "failed", "provider_message_limit"
                trimmed = client.patch(endpoint, json={"messages": messages})
                if not trimmed.is_success:
                    return "failed", "provider_rejected"
            response = client.post(
                endpoint + "/addMessage",
                json={
                    "message": {
                        "id": delivery.id,
                        "header": payload["title"],
                        "body": body,
                        "messageType": "TEXT_AND_NOTIFY",
                    }
                },
            )
        if response.status_code == 429:
            return "failed", "provider_rate_limit"
        if response.status_code >= 500:
            return "unknown", "delivery_uncertain"
        if not response.is_success:
            return "failed", "provider_rejected"
        return "success", None


PROVIDERS: dict[str, NotificationProvider] = {
    "apple": AppleWalletNotificationProvider(),
    "google": GoogleWalletNotificationProvider(),
}


def apple_message_fields(db: Session, row: m.Pass) -> list[dict]:
    state = db.get(m.PassNotificationState, row.id)
    payload = state.payload if state else {}
    # Keep the field on every newly issued pass, so the first message changes an existing value.
    fields = [
        {
            "key": "notification",
            "label": "Message / Mensaje",
            "value": f"{payload['title']}\n{payload['message']}" if payload else "",
            "changeMessage": "%@",
        }
    ]
    if payload.get("preview_text"):
        fields.append(
            {"key": "notification_preview", "label": "", "value": payload["preview_text"]}
        )
    if payload.get("url"):
        fields.append(
            {
                "key": "notification_url",
                "label": "More / Más",
                "value": payload["url"],
                "dataDetectorTypes": ["PKDataDetectorTypeLink"],
            }
        )
    return fields
